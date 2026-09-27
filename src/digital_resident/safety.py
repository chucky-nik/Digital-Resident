from __future__ import annotations

import re
from typing import Any


ACEI_DRUGS = [
    "эналаприл",
    "периндоприл",
    "лизиноприл",
    "рамиприл",
    "фозиноприл",
    "каптоприл",
    "трандолаприл",
    "зофеноприл",
]
ACEI_CLASS = ["иапф", "acei", "ингибитор апф", "ингибитор ангиотензинпревращающ"]
ARB_DRUGS = [
    "лозартан",
    "валсартан",
    "телмисартан",
    "кандесартан",
    "ирбесартан",
    "олмесартан",
    "азилсартан",
]
ARB_CLASS = ["бра", "сартан", "блокатор рецепторов ангиотензин"]
CCB = ["амлодипин", "нифедипин", "лерканидипин", "фелодипин", "верапамил", "дилтиазем", "блокатор кальциев", "(ак)"]
THIAZIDE = ["гидрохлоротиазид", "индапамид", "хлорталидон", "тиазид"]
LOOP = ["фуросемид", "торасемид", "петлев"]
MRA = ["спиронолактон", "эплеренон"]
BB = ["бисопролол", "метопролол", "небиволол", "карведилол", "бета-блок", "β-блок"]


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower())


def _has_any(text: str, keys: list[str]) -> bool:
    t = _norm(text)
    return any(k in t for k in keys)


def _is_acei_name(name: str) -> bool:
    t = _norm(name)
    if _has_any(t, ARB_DRUGS) or "бра" in t or "сартан" in t:
        # «БРА вместо иАПФ» — это не назначение иАПФ
        return False
    if "вместо" in t and "иапф" in t:
        return False
    return _has_any(t, ACEI_DRUGS) or _has_any(t, ACEI_CLASS)


def _is_arb_name(name: str) -> bool:
    t = _norm(name)
    return _has_any(t, ARB_DRUGS) or _has_any(t, ARB_CLASS)


def med_names(plan: dict[str, Any] | None, revised: dict[str, Any] | None = None) -> list[str]:
    """Только названия/дозы препаратов — без rationale (там часто слова «иАПФ» в запретах)."""
    names: list[str] = []
    for src in (plan, revised):
        if not src:
            continue
        for m in src.get("medications") or []:
            if isinstance(m, dict):
                names.append(f"{m.get('name', '')} {m.get('dose', '')} {m.get('action', '')}")
            else:
                names.append(str(m))
    return names


def meds_blob(plan: dict[str, Any] | None, revised: dict[str, Any] | None = None) -> str:
    return " | ".join(med_names(plan, revised))


def classify_regimen(text: str) -> dict[str, bool]:
    # legacy single-string path
    names = [x.strip() for x in text.split("|")] if "|" in text else [text]
    return classify_med_list(names)


def classify_med_list(names: list[str]) -> dict[str, bool]:
    return {
        "acei": any(_is_acei_name(n) for n in names),
        "arb": any(_is_arb_name(n) for n in names),
        "ccb": any(_has_any(n, CCB) for n in names),
        "thiazide": any(_has_any(n, THIAZIDE) for n in names),
        "loop": any(_has_any(n, LOOP) for n in names),
        "mra": any(_has_any(n, MRA) for n in names),
        "bb": any(_has_any(n, BB) for n in names),
    }


def allergy_blocks_acei(patient: dict[str, Any]) -> bool:
    allergies = " ".join(patient.get("allergies") or []).lower()
    notes = (patient.get("notes") or "").lower()
    blob = allergies + " " + notes
    if any(x in blob for x in ("ангио", "отёк", "отек")) and any(
        x in blob for x in ("эналаприл", "иапф", "лизиноприл", "периндоприл", "рамиприл")
    ):
        return True
    if "ангио" in blob:
        return True
    # кашель на иАПФ — тоже повод предпочесть БРА
    if "кашель" in blob and any(x in blob for x in ("иапф", "лизиноприл", "эналаприл", "периндоприл")):
        return True
    return any(x in allergies for x in ("эналаприл", "иапф")) and "кашель" in allergies


def run_safety_checks(
    patient: dict[str, Any],
    plan: dict[str, Any] | None,
    revised_plan: dict[str, Any] | None = None,
    trajectory: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Детерминированные клинические/процедурные/drug-drug проверки."""
    findings: list[dict[str, Any]] = []
    labs0 = patient.get("labs_day0") or {}
    egfr0 = float(labs0.get("egfr") or 999)
    k0 = float(labs0.get("k_mmol_l") or 0)
    names = med_names(plan, revised_plan)
    clas = classify_med_list(names)
    blob = " | ".join(names)
    traj = trajectory or []

    # --- allergies / contraindications ---
    if allergy_blocks_acei(patient) and clas["acei"]:
        findings.append(
            {
                "severity": "clinical",
                "severity": "high",
                "title": "иАПФ при ангионевротическом отёке / аллергии на иАПФ",
                "detail": (
                    "В анамнезе реакция на иАПФ (ангиоотёк). По КР это абсолютное "
                    "противопоказание к иАПФ; предпочтителен БРА."
                ),
                "evidence": "patient.allergies + medications",
                "guideline": "КР АГ 2024 §3.4.2: ангионевротический отёк в анамнезе — противопоказание к иАПФ/БРА? (иАПФ — да; выбор БРА)",
                "recommendation": "Исключить иАПФ; использовать БРА при отсутствии иных противопоказаний.",
                "rule_id": "ACEI_ANGIOEDEMA",
            }
        )

    if k0 >= 5.5 and (clas["acei"] or clas["arb"] or clas["mra"]):
        findings.append(
            {
                "severity": "clinical",
                "severity": "high",
                "title": "иРААС/АМКР при исходной гиперкалиемии",
                "detail": f"K+ день0 = {k0} ммоль/л ≥5.5 — абсолютное противопоказание к иАПФ/БРА.",
                "evidence": "labs_day0.k_mmol_l + medications",
                "guideline": "КР АГ 2024: не рекомендуется иАПФ/БРА при K+≥5.5 ммоль/л",
                "recommendation": "Не стартовать иРААС до коррекции калия; мониторинг.",
                "rule_id": "IRAAS_HYPERK_BASELINE",
            }
        )

    # --- drug-drug conflicts ---
    if clas["acei"] and clas["arb"]:
        findings.append(
            {
                "severity": "clinical",
                "severity": "high",
                "title": "Drug-drug: двойная блокада РААС (иАПФ + БРА)",
                "detail": (
                    "Комбинация двух иРААС повышает риск гиперкалиемии, гипотензии "
                    "и ухудшения функции почек и не рекомендуется."
                ),
                "evidence": "medications contain ACEI+ARB",
                "guideline": "КР АГ 2024 §3.4.1: не рекомендуется комбинация двух иРААС (ЕОК/ЕОАГ 3А)",
                "recommendation": "Оставить один иРААС (иАПФ или БРА), не комбинировать.",
                "rule_id": "DD_DUAL_RAAS",
            }
        )

    if (clas["acei"] or clas["arb"]) and clas["mra"]:
        findings.append(
            {
                "severity": "clinical",
                "severity": "high",
                "title": "Drug-drug: иРААС + спиронолактон (риск гиперкалиемии)",
                "detail": (
                    "Сочетание иРААС с АМКР повышает риск гиперкалиемии, особенно при ХБП; "
                    "нужен жёсткий мониторинг K+ и рСКФ."
                ),
                "evidence": "medications contain IRAAS+MRA",
                "guideline": "КР АГ 2024: риск гиперкалиемии спиронолактона выше при добавлении к иРААС",
                "recommendation": "Проверить показание (резистентная АГ), контролировать K+/СКФ; при K+≥5 или СКФ≤30 — не назначать.",
                "rule_id": "DD_IRAAS_MRA",
            }
        )

    if clas["mra"] and (egfr0 <= 30 or k0 >= 5.0):
        findings.append(
            {
                "severity": "clinical",
                "severity": "high",
                "title": "Спиронолактон при СКФ≤30 или K+≥5",
                "detail": f"рСКФ={egfr0}, K+={k0}. Спиронолактон противопоказан при СКФ≤30 и K+≥5.",
                "evidence": "labs_day0 + MRA in plan",
                "guideline": "КР АГ 2024: спиронолактон противопоказан при СКФ≤30 и K+≥5",
                "recommendation": "Не назначать АМКР; выбрать альтернативу.",
                "rule_id": "MRA_CKD_K",
            }
        )

    if clas["thiazide"] and egfr0 < 30:
        findings.append(
            {
                "severity": "clinical",
                "severity": "high",
                "title": "Тиазидный диуретик при рСКФ <30",
                "detail": (
                    f"рСКФ={egfr0} <30: тиазиды противопоказаны/неэффективны; "
                    "нужны петлевые диуретики."
                ),
                "evidence": "labs_day0.egfr + thiazide",
                "guideline": "КР АГ 2024: тиазиды противопоказаны при ClCr <30; альтернатива — петлевые",
                "recommendation": "Заменить на петлевой диуретик.",
                "rule_id": "THIAZIDE_LOW_GFR",
            }
        )
    elif clas["thiazide"] and egfr0 < 45:
        findings.append(
            {
                "severity": "clinical",
                "severity": "medium",
                "title": "Тиазид при рСКФ <45 — рассмотреть петлевой диуретик",
                "detail": f"рСКФ={egfr0}: по КР петлевые можно рассматривать индивидуально при СКФ<45.",
                "evidence": "labs_day0.egfr + thiazide",
                "guideline": "КР АГ 2024: петлевые диуретики можно рассматривать при СКФ<45",
                "recommendation": "Оценить замену/добавление петлевого диуретика и мониторинг.",
                "rule_id": "THIAZIDE_GFR45",
            }
        )

    # --- procedural ---
    if not patient.get("consent_invasive", True):
        findings.append(
            {
                "severity": "procedural",
                "severity": "high",
                "title": "Нет информированного согласия на инвазивные процедуры",
                "detail": "Процедурный дефект: до инвазивных вмешательств необходимо получить и зафиксировать информированное согласие.",
                "evidence": "patient.consent_invasive",
                "guideline": "Процедурный чек-лист СППР / стандарты оказания помощи",
                "recommendation": "Получить и зафиксировать согласие до инвазивных процедур.",
                "rule_id": "PROC_CONSENT",
            }
        )

    # GFR check before nephrotoxic / IRAAS start
    monitoring = " ".join(
        str(x) for x in ((plan or {}).get("monitoring") or [])
    ).lower()
    procedural = " ".join(
        str(x) for x in ((plan or {}).get("procedural_checklist") or [])
    ).lower()
    mon_blob = monitoring + " " + procedural
    needs_lab_monitor = clas["acei"] or clas["arb"] or clas["mra"] or egfr0 < 60
    has_lab_monitor = any(
        k in mon_blob for k in ("скф", "креатинин", "калий", "k+", "gfr", "рскф")
    )
    if needs_lab_monitor and not has_lab_monitor:
        findings.append(
            {
                "severity": "procedural",
                "severity": "high",
                "title": "Нет плана контроля рСКФ/калия до/после иРААС",
                "detail": (
                    "Перед и после старта нефротропной/иРААС-терапии требуется контроль "
                    "креатинина/рСКФ и калия — в плане мониторинг не зафиксирован."
                ),
                "evidence": "medications vs monitoring/procedural_checklist",
                "guideline": "КР АГ 2024: мониторинг K+ и функции почек на иРААС/АМКР",
                "recommendation": "Добавить контроль K+ и рСКФ до старта и через 3–14 дней.",
                "rule_id": "PROC_GFR_K_MONITOR",
            }
        )

    # --- trajectory complications ---
    for p in traj:
        flags = set(p.get("flags") or [])
        labs = p.get("labs") or {}
        if "hyperkalemia" in flags or float(labs.get("k_mmol_l") or 0) >= 5.5:
            if not revised_plan:
                findings.append(
                    {
                        "severity": "clinical",
                        "severity": "high",
                        "title": "Гиперкалиемия без пересмотра плана",
                        "detail": f"День {p.get('day')}: K+={labs.get('k_mmol_l')} — требуется коррекция иРААС.",
                        "evidence": f"trajectory day {p.get('day')}",
                        "guideline": "КР АГ 2024: иАПФ/БРА не рекомендуются при K+≥5.5",
                        "recommendation": "Пересчитать план: hold/reduce иРААС, контроль K+/СКФ.",
                        "rule_id": "TRAJ_HYPERK_NO_REPLAN",
                    }
                )
            else:
                findings.append(
                    {
                        "severity": "clinical",
                        "severity": "high",
                        "title": "Гиперкалиемия на фоне терапии — нужна коррекция",
                        "detail": f"День {p.get('day')}: K+={labs.get('k_mmol_l')}, рСКФ={labs.get('egfr')}.",
                        "evidence": f"trajectory day {p.get('day')} + revised_plan",
                        "guideline": "КР АГ 2024: противопоказание иАПФ/БРА при гиперкалиемии ≥5.5",
                        "recommendation": "Подтвердить отмену/редукцию иРААС и мониторинг.",
                        "rule_id": "TRAJ_HYPERK",
                    }
                )
        if "rising_potassium" in flags and float(labs.get("k_mmol_l") or 0) >= 5.0:
            findings.append(
                {
                    "severity": "clinical",
                    "severity": "medium",
                    "title": "Нарастание калия на фоне иРААС у пациента с ХБП",
                    "detail": f"День {p.get('day')}: K+={labs.get('k_mmol_l')} — усилить мониторинг, оценить дозу.",
                    "evidence": f"trajectory flags rising_potassium day {p.get('day')}",
                    "guideline": "КР АГ 2024: мониторинг K+/СКФ при ХБП и иРААС",
                    "recommendation": "Участить контроль, не эскалировать дозу без лаборатории.",
                    "rule_id": "TRAJ_RISING_K",
                }
            )

    # dedupe by rule_id/title
    uniq: list[dict[str, Any]] = []
    seen: set[str] = set()
    for f in findings:
        key = f.get("rule_id") or f.get("title")
        if key in seen:
            continue
        seen.add(str(key))
        uniq.append(f)
    return uniq


def enforce_plan_constraints(patient: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    """Пост-правка плана: убрать иАПФ при ангиоотёке; добавить мониторинг при иРААС."""
    if not isinstance(plan, dict) or plan.get("parse_error"):
        return plan
    out = dict(plan)
    meds = list(out.get("medications") or [])
    changed = []

    if allergy_blocks_acei(patient):
        new_meds = []
        for m in meds:
            name = m.get("name", "") if isinstance(m, dict) else str(m)
            if _is_acei_name(name) and not _is_arb_name(name):
                if isinstance(m, dict):
                    nm = dict(m)
                    nm["name"] = "БРА (лозартан/валсартан) — вместо иАПФ"
                    nm["rationale"] = (
                        (nm.get("rationale") or "")
                        + " | Автокоррекция: ангиоотёк на иАПФ → БРА по КР."
                    ).strip(" |")
                    nm["safety_override"] = "ACEI_TO_ARB_ANGIOEDEMA"
                    new_meds.append(nm)
                    changed.append("ACEI→ARB из-за ангиоотёка")
                else:
                    new_meds.append(
                        {
                            "name": "БРА (вместо иАПФ)",
                            "dose": "по инструкции",
                            "rationale": "Ангиоотёк на иАПФ — предпочтителен БРА",
                            "citations": [],
                            "safety_override": "ACEI_TO_ARB_ANGIOEDEMA",
                        }
                    )
                    changed.append("ACEI→ARB из-за ангиоотёка")
            else:
                new_meds.append(m)
        meds = new_meds
        out["medications"] = meds

    clas = classify_med_list(med_names(out, None))
    monitoring = list(out.get("monitoring") or [])
    mon_txt = _norm(str(monitoring))
    if (clas["acei"] or clas["arb"] or clas["mra"]) and not any(
        k in mon_txt for k in ("калий", "скф", "креатинин", "k+")
    ):
        monitoring.append(
            {
                "item": "Контроль калия и рСКФ до старта и через 3–14 дней после иРААС/АМКР",
                "citations": [],
                "safety_override": "ADD_K_GFR_MONITOR",
            }
        )
        changed.append("добавлен мониторинг K+/рСКФ")
        out["monitoring"] = monitoring

    checklist = list(out.get("procedural_checklist") or [])
    if not patient.get("consent_invasive", True):
        checklist.append(
            {
                "item": "Информированное согласие на инвазивные процедуры",
                "status": "missing",
                "safety_override": "FLAG_CONSENT_MISSING",
            }
        )
        out["procedural_checklist"] = checklist

    if changed:
        out["safety_overrides"] = changed
    return out
