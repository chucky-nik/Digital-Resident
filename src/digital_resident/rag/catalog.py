"""Каталог документов КР: какой файл подтягивать под диагноз."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from digital_resident.config import settings

# Зарегистрированные документы в data/guidelines.
# При появлении новых PDF — добавить сюда match-ключи.
GUIDELINE_CATALOG: list[dict[str, Any]] = [
    {
        "id": "ag_2024",
        "title": "КР «Артериальная гипертензия у взрослых» 2024",
        "org": "РКО / Минздрав РФ",
        "doc_id": "62_3",
        "pdf": "kr62_3_ag_vzroslye2024.pdf",
        "txt": "kr_ag_2024.txt",
        "match": [
            "гипертенз",
            "гипертони",
            " аг ",
            "аг,",
            "аг;",
            "аг.",
            "аг ",
            "i10",
            "i11",
            "i12",
            "i13",
            "ад ",
            "артериальн",
            "давлен",
            "хбп",
            "ибс",
            "иапф",
            "бра",
        ],
    },
]


def _blob(diagnosis: str, comorbidities: list[str] | None = None) -> str:
    parts = [diagnosis or ""]
    parts.extend(comorbidities or [])
    return " ".join(parts).lower()


def docs_for_diagnosis(
    diagnosis: str,
    comorbidities: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Документы каталога, подходящие под диагноз (или все АГ-дефолт)."""
    blob = f" {_blob(diagnosis, comorbidities)} "
    guidelines = settings()["guideline_txt"].parent
    matched: list[dict[str, Any]] = []
    for doc in GUIDELINE_CATALOG:
        keys = doc.get("match") or []
        if any(k in blob for k in keys):
            matched.append(_enrich(doc, guidelines))
    if not matched:
        # пока в индексе только АГ — показываем его как базовый протокол стенда
        for doc in GUIDELINE_CATALOG:
            if doc["id"] == "ag_2024":
                item = _enrich(doc, guidelines)
                item["fallback"] = True
                matched.append(item)
                break
    return matched


def _enrich(doc: dict[str, Any], guidelines: Path) -> dict[str, Any]:
    pdf = guidelines / doc["pdf"]
    return {
        **doc,
        "pdf_path": str(pdf),
        "exists": pdf.exists(),
    }


def diagnosis_fingerprint(
    diagnosis: str,
    comorbidities: list[str] | None = None,
    allergies: list[str] | None = None,
) -> str:
    """Стабильный ключ кэша при смене диагноза."""
    return "|".join(
        [
            (diagnosis or "").strip().lower(),
            ",".join(sorted((c or "").strip().lower() for c in (comorbidities or []))),
            ",".join(sorted((a or "").strip().lower() for a in (allergies or []))),
        ]
    )
