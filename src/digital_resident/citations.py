from __future__ import annotations

import re
from typing import Any


def citation_catalog(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Нумерованный каталог допустимых цитат [1]..[N] строго из RAG-хитов."""
    catalog = []
    for i, h in enumerate(hits, 1):
        catalog.append(
            {
                "ref": f"[{i}]",
                "chunk_id": h.get("chunk_id") or h.get("id") or "",
                "section": h.get("section", ""),
                "page": h.get("page", ""),
                "source": h.get("source", ""),
                "citation": h.get("citation", ""),
                "text_preview": (h.get("text") or "")[:220],
            }
        )
    return catalog


def format_citation_rules(hits: list[dict[str, Any]]) -> str:
    lines = [
        "ПРАВИЛА ЦИТИРОВАНИЯ (обязательны):",
        "1) Разрешены ТОЛЬКО ссылки из списка ниже: [1], [2], ...",
        "2) В citations_used для каждого ref укажи section и page РОВНО как в списке.",
        "3) Нельзя ссылаться на несуществующие пункты/страницы.",
        "4) Если факта нет во фрагментах — не назначай и напиши uncertainty.",
        "",
        "Допустимые источники:",
    ]
    for c in citation_catalog(hits):
        lines.append(
            f"{c['ref']} section=\"{c['section']}\" page={c['page']} "
            f"chunk_id={c['chunk_id']} | {c['text_preview']}..."
        )
    return "\n".join(lines)


_REF_RE = re.compile(r"\[(\d+)\]")


def extract_refs(value: Any) -> list[str]:
    found: list[str] = []
    if value is None:
        return found
    if isinstance(value, list):
        for x in value:
            found.extend(extract_refs(x))
        return found
    if isinstance(value, dict):
        for x in value.values():
            found.extend(extract_refs(x))
        return found
    for m in _REF_RE.finditer(str(value)):
        found.append(f"[{m.group(1)}]")
    return found


def validate_and_repair_plan(
    plan: dict[str, Any],
    hits: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """
    Проверяет, что все [N] есть в RAG-контексте.
    Невалидные ссылки удаляет; citations_used пересобирает из каталога.
    Возвращает (plan, citation_issues).
    """
    if not isinstance(plan, dict):
        return {"parse_error": True, "raw": str(plan)}, [
            {"severity": "high", "title": "План не JSON-объект", "detail": "parse_error"}
        ]

    catalog = {c["ref"]: c for c in citation_catalog(hits)}
    issues: list[dict[str, Any]] = []
    used_refs: set[str] = set()

    def clean_item_citations(item: Any) -> Any:
        if not isinstance(item, dict):
            return item
        cites = item.get("citations")
        if cites is None:
            return item
        if not isinstance(cites, list):
            cites = extract_refs(cites)
        ok = []
        for c in cites:
            refs = extract_refs(c) or ([c] if isinstance(c, str) and c.startswith("[") else [])
            for ref in refs:
                if ref in catalog:
                    ok.append(ref)
                    used_refs.add(ref)
                else:
                    issues.append(
                        {
                            "category": "citation",
                            "severity": "high",
                            "title": "Недопустимая цитата вне RAG-контекста",
                            "detail": f"Ссылка {ref} отсутствует среди переданных фрагментов КР.",
                            "evidence": str(item)[:240],
                            "recommendation": "Удалить ссылку или перезапросить RAG по нужному разделу.",
                        }
                    )
        item = dict(item)
        item["citations"] = sorted(set(ok), key=lambda x: int(x.strip("[]")))
        if not item["citations"] and any(
            k in item for k in ("name", "item", "dose", "rationale")
        ):
            issues.append(
                {
                    "category": "citation",
                    "severity": "medium",
                    "title": "Назначение/пункт без валидной цитаты",
                    "detail": "После валидации не осталось допустимых ссылок [N].",
                    "evidence": str(item)[:240],
                    "recommendation": "Привязать пункт к релевантному фрагменту КР.",
                }
            )
        # semantic: medication cite should mention drug/class or dose table
        if item.get("name") and item.get("citations"):
            name_l = str(item.get("name") or "").lower()
            tokens = [
                t
                for t in re.split(r"[^\wа-яА-ЯёЁ]+", name_l)
                if len(t) >= 4
            ]
            class_tokens = [
                "иапф",
                "бра",
                "сартан",
                "амлодипин",
                "диуретик",
                "тиазид",
                "спиронолактон",
                "комбинац",
                "доз",
                "мг",
                "ираас",
                "гипертенз",
            ]
            hit_ok = False
            for ref in item["citations"]:
                meta = catalog.get(ref) or {}
                # need full text — look up from hits
                blob = " ".join(
                    str(meta.get(k) or "") for k in ("section", "text_preview", "chunk_id")
                ).lower()
                for h in hits:
                    cid = h.get("chunk_id") or h.get("id")
                    if cid == meta.get("chunk_id"):
                        blob += " " + (h.get("text") or "").lower()
                        break
                if any(t in blob for t in tokens) or any(t in blob for t in class_tokens):
                    hit_ok = True
                    break
            if not hit_ok:
                issues.append(
                    {
                        "category": "citation",
                        "severity": "medium",
                        "title": "Цитата не подтверждает препарат/дозу",
                        "detail": (
                            f"Для «{item.get('name')}» ссылки {item['citations']} "
                            "не содержат имени/класса препарата или дозовой таблицы."
                        ),
                        "evidence": str(item)[:240],
                        "recommendation": "Цитировать фрагмент про классы АГП / справочник доз.",
                    }
                )
        return item

    out = dict(plan)
    for key in ("examinations", "medications", "monitoring"):
        if isinstance(out.get(key), list):
            out[key] = [clean_item_citations(x) for x in out[key]]

    # rebuild citations_used strictly from catalog
    out["citations_used"] = [
        {
            "ref": catalog[r]["ref"],
            "section": catalog[r]["section"],
            "page": catalog[r]["page"],
            "chunk_id": catalog[r]["chunk_id"],
            "source": catalog[r]["source"],
        }
        for r in sorted(used_refs, key=lambda x: int(x.strip("[]")))
        if r in catalog
    ]
    out["citation_validation"] = {
        "allowed_refs": list(catalog.keys()),
        "used_refs": sorted(used_refs, key=lambda x: int(x.strip("[]"))),
        "invalid_removed": len([i for i in issues if i.get("title", "").startswith("Недопустимая")]),
    }
    return out, issues
