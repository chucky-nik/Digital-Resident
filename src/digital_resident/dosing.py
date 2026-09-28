"""Формуляр стартовых доз АГП + парсинг/валидация (детерминированный слой).

Диапазоны — типичные взрослые стартовые/терапевтические дозы по практике КР АГ
и инструкций (прототип CDS; не замена врачу). Цель — отсечь вредные/пустые дозы.
"""
from __future__ import annotations

import re
from typing import Any


# id -> formulary card
# max_mg = максимальная разовая/суточная типичная доза для прототипа (reject выше)
FORMULARY: dict[str, dict[str, Any]] = {
    "периндоприл": {
        "aliases": ["периндоприл", "perindopril", "престариум"],
        "class": "acei",
        "unit": "mg",
        "start_mg": 5.0,
        "min_mg": 2.5,
        "max_mg": 10.0,
        "freq": "1 р/сут",
        "ckd_egfr_lt_30_max_mg": 2.5,
        "label": "Периндоприл",
    },
    "эналаприл": {
        "aliases": ["эналаприл", "enalapril", "ренитек"],
        "class": "acei",
        "unit": "mg",
        "start_mg": 5.0,
        "min_mg": 2.5,
        "max_mg": 40.0,
        "freq": "1–2 р/сут",
        "ckd_egfr_lt_30_max_mg": 5.0,
        "label": "Эналаприл",
    },
    "лизиноприл": {
        "aliases": ["лизиноприл", "lisinopril"],
        "class": "acei",
        "unit": "mg",
        "start_mg": 10.0,
        "min_mg": 2.5,
        "max_mg": 40.0,
        "freq": "1 р/сут",
        "ckd_egfr_lt_30_max_mg": 5.0,
        "label": "Лизиноприл",
    },
    "рамиприл": {
        "aliases": ["рамиприл", "ramipril"],
        "class": "acei",
        "unit": "mg",
        "start_mg": 2.5,
        "min_mg": 1.25,
        "max_mg": 10.0,
        "freq": "1 р/сут",
        "ckd_egfr_lt_30_max_mg": 1.25,
        "label": "Рамиприл",
    },
    "валсартан": {
        "aliases": ["валсартан", "valsartan"],
        "class": "arb",
        "unit": "mg",
        "start_mg": 80.0,
        "min_mg": 40.0,
        "max_mg": 320.0,
        "freq": "1 р/сут",
        "ckd_egfr_lt_30_max_mg": 80.0,
        "label": "Валсартан",
    },
    "лозартан": {
        "aliases": ["лозартан", "losartan"],
        "class": "arb",
        "unit": "mg",
        "start_mg": 50.0,
        "min_mg": 25.0,
        "max_mg": 100.0,
        "freq": "1 р/сут",
        "ckd_egfr_lt_30_max_mg": 50.0,
        "label": "Лозартан",
    },
    "телмисартан": {
        "aliases": ["телмисартан", "telmisartan"],
        "class": "arb",
        "unit": "mg",
        "start_mg": 40.0,
        "min_mg": 20.0,
        "max_mg": 80.0,
        "freq": "1 р/сут",
        "label": "Телмисартан",
    },
    "кандесартан": {
        "aliases": ["кандесартан", "candesartan"],
        "class": "arb",
        "unit": "mg",
        "start_mg": 8.0,
        "min_mg": 4.0,
        "max_mg": 32.0,
        "freq": "1 р/сут",
        "label": "Кандесартан",
    },
    "амлодипин": {
        "aliases": ["амлодипин", "amlodipine", "норваск"],
        "class": "ccb",
        "unit": "mg",
        "start_mg": 5.0,
        "min_mg": 2.5,
        "max_mg": 10.0,
        "freq": "1 р/сут",
        "label": "Амлодипин",
    },
    "индапамид": {
        "aliases": ["индапамид", "indapamide"],
        "class": "thiazide",
        "unit": "mg",
        "start_mg": 1.5,
        "min_mg": 1.25,
        "max_mg": 2.5,
        "freq": "1 р/сут",
        "label": "Индапамид",
    },
    "гидрохлоротиазид": {
        "aliases": ["гидрохлоротиазид", "hydrochlorothiazide", "гхт"],
        "class": "thiazide",
        "unit": "mg",
        "start_mg": 12.5,
        "min_mg": 12.5,
        "max_mg": 25.0,
        "freq": "1 р/сут",
        "label": "Гидрохлоротиазид",
    },
    "фуросемид": {
        "aliases": ["фуросемид", "furosemide", "лазикс"],
        "class": "loop",
        "unit": "mg",
        "start_mg": 40.0,
        "min_mg": 20.0,
        "max_mg": 80.0,
        "freq": "1–2 р/сут",
        "label": "Фуросемид",
    },
    "торасемид": {
        "aliases": ["торасемид", "torasemide"],
        "class": "loop",
        "unit": "mg",
        "start_mg": 5.0,
        "min_mg": 2.5,
        "max_mg": 20.0,
        "freq": "1 р/сут",
        "label": "Торасемид",
    },
    "спиронолактон": {
        "aliases": ["спиронолактон", "spironolactone", "верошпирон"],
        "class": "mra",
        "unit": "mg",
        "start_mg": 25.0,
        "min_mg": 12.5,
        "max_mg": 50.0,
        "freq": "1 р/сут",
        "label": "Спиронолактон",
    },
    "бисопролол": {
        "aliases": ["бисопролол", "bisoprolol"],
        "class": "bb",
        "unit": "mg",
        "start_mg": 5.0,
        "min_mg": 1.25,
        "max_mg": 10.0,
        "freq": "1 р/сут",
        "label": "Бисопролол",
    },
}

# фиксированные комбинации: компоненты и стартовые мг
FIXED_COMBOS: list[dict[str, Any]] = [
    {
        "aliases": ["периндоприл", "амлодипин"],
        "label": "Периндоприл + Амлодипин",
        "components": [("периндоприл", 5.0), ("амлодипин", 5.0)],
        "dose_str": "5 мг + 5 мг 1 р/сут",
    },
    {
        "aliases": ["периндоприл", "индапамид"],
        "label": "Периндоприл + Индапамид",
        "components": [("периндоприл", 5.0), ("индапамид", 1.25)],
        "dose_str": "5 мг + 1.25 мг 1 р/сут",
    },
    {
        "aliases": ["валсартан", "амлодипин"],
        "label": "Валсартан + Амлодипин",
        "components": [("валсартан", 80.0), ("амлодипин", 5.0)],
        "dose_str": "80 мг + 5 мг 1 р/сут",
    },
    {
        "aliases": ["лозартан", "амлодипин"],
        "label": "Лозартан + Амлодипин",
        "components": [("лозартан", 50.0), ("амлодипин", 5.0)],
        "dose_str": "50 мг + 5 мг 1 р/сут",
    },
]

_VAGUE = re.compile(
    r"(начальн|по\s+инструкц|титрац|корректир|снижени|отмена\s+или|"
    r"по\s+показан|индивидуальн|стандартн|обычн\s+доз|"
    r"dose\s+as|as\s+needed|tbd|н/д|не\s+указан)",
    re.I,
)
_MG_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*мг", re.I)
_ZERO_MG = re.compile(r"(?:^|[^\d])0\s*мг", re.I)


def formulary_text_for_rag() -> str:
    lines = [
        "Справочник стартовых доз АГП для взрослых (прототип CDS по КР АГ 2024 / типовые режимы):"
    ]
    for card in FORMULARY.values():
        ckd = card.get("ckd_egfr_lt_30_max_mg")
        extra = f"; при рСКФ<30 макс. старт ≈{ckd} мг" if ckd else ""
        lines.append(
            f"- {card['label']}: старт {card['start_mg']} мг ({card['freq']}), "
            f"диапазон {card['min_mg']}–{card['max_mg']} мг/сут{extra}."
        )
    lines.append(
        "Фиксированные комбинации (пример старта): периндоприл+амлодипин 5+5 мг; "
        "валсартан+амлодипин 80+5 мг; лозартан+амлодипин 50+5 мг."
    )
    lines.append(
        "При K+≥5.5 ммоль/л иРААС (иАПФ/БРА) и спиронолактон — отмена (action=stop), "
        "не «снижение или отмена»."
    )
    return " ".join(lines)


def match_drug(name: str) -> str | None:
    t = (name or "").lower()
    best = None
    best_len = 0
    for key, card in FORMULARY.items():
        for al in card["aliases"]:
            if al in t and len(al) > best_len:
                best, best_len = key, len(al)
    return best


def match_fixed_combo(name: str) -> dict[str, Any] | None:
    t = (name or "").lower()
    for combo in FIXED_COMBOS:
        if all(a in t for a in combo["aliases"]):
            return combo
    return None


def parse_mg_values(dose: str) -> list[float]:
    vals = []
    for m in _MG_RE.finditer(dose or ""):
        vals.append(float(m.group(1).replace(",", ".")))
    return vals


def is_stop_action(med: dict[str, Any]) -> bool:
    action = str(med.get("action") or "").lower()
    dose = str(med.get("dose") or "").lower()
    name = str(med.get("name") or "").lower()
    if action in ("stop", "hold", "отмена", "отменить"):
        return True
    if "отмен" in dose and "или" not in dose:
        return True
    if "отмен" in name and "вместо" not in name:
        return True
    return False


def is_vague_dose(dose: str) -> bool:
    d = (dose or "").strip()
    if not d:
        return True
    if _ZERO_MG.search(d):
        return True
    if parse_mg_values(d):
        # «отмена или снижение» даже с мг — хедж
        if re.search(r"отмена\s+или|или\s+снижен", d, re.I):
            return True
        return False
    return bool(_VAGUE.search(d)) or True


def default_dose_str(drug_key: str, *, egfr: float | None = None) -> str:
    card = FORMULARY[drug_key]
    mg = float(card["start_mg"])
    if egfr is not None and egfr < 30 and card.get("ckd_egfr_lt_30_max_mg"):
        mg = min(mg, float(card["ckd_egfr_lt_30_max_mg"]))
    return f"{mg:g} мг {card['freq']}"


def validate_medication_dose(
    med: dict[str, Any],
    *,
    egfr: float | None = None,
) -> list[dict[str, Any]]:
    """Возвращает список issues по одному препарату."""
    issues: list[dict[str, Any]] = []
    if not isinstance(med, dict):
        return issues
    if is_stop_action(med):
        return issues

    name = str(med.get("name") or "")
    dose = str(med.get("dose") or "")
    combo = match_fixed_combo(name)
    drug = match_drug(name)

    if is_vague_dose(dose):
        issues.append(
            {
                "category": "clinical",
                "severity": "high",
                "title": "Неконкретная / отсутствующая доза",
                "detail": f"{name}: «{dose or '—'}» — нужна числовая доза в мг из формуляра.",
                "evidence": f"medication={name!r} dose={dose!r}",
                "guideline": "Формуляр стартовых доз CDS / КР АГ 2024",
                "recommendation": "Указать мг (например 5 мг 1 р/сут) или пометить uncertainty.",
                "rule_id": "DOSE_VAGUE",
            }
        )
        return issues

    mgs = parse_mg_values(dose)
    if combo:
        # ожидаем 2 числа в разумных пределах компонентов
        for (comp_key, start), mg in zip(combo["components"], mgs + [None] * 2):
            if mg is None:
                continue
            card = FORMULARY[comp_key]
            max_mg = float(card["max_mg"])
            if egfr is not None and egfr < 30 and card.get("ckd_egfr_lt_30_max_mg"):
                max_mg = min(max_mg, float(card["ckd_egfr_lt_30_max_mg"]))
            if mg < float(card["min_mg"]) * 0.5 or mg > max_mg * 1.5:
                issues.append(
                    {
                        "category": "clinical",
                        "severity": "high",
                        "title": f"Доза вне безопасного диапазона ({card['label']})",
                        "detail": (
                            f"{name}: {mg} мг при допустимом "
                            f"{card['min_mg']}–{max_mg} мг для {card['label']}."
                        ),
                        "evidence": f"dose={dose!r}",
                        "guideline": "Формуляр CDS / типовые режимы КР АГ",
                        "recommendation": f"Скорректировать до {card['start_mg']:g} мг ({card['freq']}).",
                        "rule_id": "DOSE_OUT_OF_RANGE",
                    }
                )
        return issues

    if not drug:
        # неизвестный препарат с числовой дозой — warning medium
        if any(mg > 500 for mg in mgs):
            issues.append(
                {
                    "category": "clinical",
                    "severity": "high",
                    "title": "Подозрительно высокая доза неизвестного препарата",
                    "detail": f"{name}: {dose}",
                    "evidence": f"dose={dose!r}",
                    "guideline": "Формуляр CDS",
                    "recommendation": "Проверить препарат и дозу вручную.",
                    "rule_id": "DOSE_SUSPICIOUS",
                }
            )
        return issues

    card = FORMULARY[drug]
    max_mg = float(card["max_mg"])
    if egfr is not None and egfr < 30 and card.get("ckd_egfr_lt_30_max_mg"):
        max_mg = min(max_mg, float(card["ckd_egfr_lt_30_max_mg"]))
    for mg in mgs:
        if mg < float(card["min_mg"]) * 0.5 or mg > max_mg:
            issues.append(
                {
                    "category": "clinical",
                    "severity": "high",
                    "title": f"Доза вне безопасного диапазона ({card['label']})",
                    "detail": (
                        f"{name}: {mg} мг; допустимо {card['min_mg']}–{max_mg} мг "
                        f"({card['freq']})."
                    ),
                    "evidence": f"dose={dose!r}",
                    "guideline": "Формуляр CDS / типовые режимы КР АГ",
                    "recommendation": (
                        f"Использовать стартовую {card['start_mg']:g} мг {card['freq']}."
                    ),
                    "rule_id": "DOSE_OUT_OF_RANGE",
                }
            )
    return issues


def repair_medication_dose(
    med: dict[str, Any],
    *,
    egfr: float | None = None,
) -> dict[str, Any]:
    """Подставляет безопасную стартовую дозу из формуляра при vague/out-of-range."""
    if not isinstance(med, dict) or is_stop_action(med):
        return med
    out = dict(med)
    name = str(out.get("name") or "")
    dose = str(out.get("dose") or "")
    combo = match_fixed_combo(name)
    drug = match_drug(name)
    issues = validate_medication_dose(out, egfr=egfr)
    if not issues:
        return out

    if combo:
        out["dose"] = combo["dose_str"]
        out["name"] = combo["label"]
        out["dose_repair"] = "FORMULARY_FIXED_COMBO"
        return out

    if drug:
        # если out-of-range — clamp к старту; если vague — старт
        out["dose"] = default_dose_str(drug, egfr=egfr)
        # нормализуем имя к label если это однокомпонентный препарат
        if match_drug(name) and not combo:
            # сохраняем пользовательское имя если уже конкретное
            if FORMULARY[drug]["label"].lower() not in name.lower():
                out["name"] = FORMULARY[drug]["label"]
        out["dose_repair"] = "FORMULARY_START"
        return out

    # неизвестный + vague → uncertainty
    if is_vague_dose(dose):
        out["dose"] = ""
        out["dose_unknown"] = True
        unc = list(out.get("uncertainties") or []) if isinstance(out.get("uncertainties"), list) else []
        out.setdefault("_plan_uncertainty", "dose_unknown")
        out["dose_repair"] = "MARK_UNKNOWN"
    return out


def validate_and_repair_plan_doses(
    plan: dict[str, Any],
    patient: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Валидирует и чинит дозы в medications; возвращает (plan, residual_issues)."""
    if not isinstance(plan, dict) or plan.get("parse_error"):
        return plan, []
    egfr = None
    if patient:
        egfr = float((patient.get("labs_day0") or {}).get("egfr") or 999)
    out = dict(plan)
    meds = []
    residual: list[dict[str, Any]] = []
    repaired = []
    for m in out.get("medications") or []:
        if not isinstance(m, dict):
            meds.append(m)
            continue
        before = dict(m)
        fixed = repair_medication_dose(m, egfr=egfr)
        # повторная проверка
        still = validate_medication_dose(fixed, egfr=egfr)
        if still and fixed.get("dose_unknown"):
            residual.extend(still)
        elif still:
            # не смогли починить полностью
            residual.extend(still)
        if fixed.get("dose_repair"):
            repaired.append(f"{before.get('name')}: {before.get('dose')} → {fixed.get('dose')}")
        meds.append(fixed)
    out["medications"] = meds
    if repaired:
        prev = list(out.get("safety_overrides") or [])
        out["safety_overrides"] = prev + [f"dose_repair: {x}" for x in repaired]
    # plan-level uncertainty
    if any(isinstance(m, dict) and m.get("dose_unknown") for m in meds):
        unc = list(out.get("uncertainties") or [])
        unc.append("Есть препараты без верифицированной дозы в мг (dose_unknown).")
        out["uncertainties"] = unc
    return out, residual


def enforce_iraas_stop_on_hyperkalemia(
    plan: dict[str, Any],
    trajectory: list[dict[str, Any]] | None = None,
    *,
    k_threshold: float = 5.5,
) -> dict[str, Any]:
    """При K+≥threshold — жёсткий action=stop для активного иРААС/АМКР, без хеджа."""
    if not isinstance(plan, dict) or plan.get("parse_error"):
        return plan
    traj = trajectory or []
    triggered = False
    trigger_day = None
    k_val = None
    for p in traj:
        labs = p.get("labs") or {}
        k = float(labs.get("k_mmol_l") or 0)
        flags = set(p.get("flags") or [])
        if "hyperkalemia" in flags or k >= k_threshold:
            triggered = True
            trigger_day = p.get("day")
            k_val = k
            break
    if not triggered:
        return plan

    from digital_resident.safety import _is_acei_name, _is_arb_name, _has_any, MRA

    out = dict(plan)
    meds = []
    changed = False
    for m in out.get("medications") or []:
        if not isinstance(m, dict):
            meds.append(m)
            continue
        nm = dict(m)
        name = str(nm.get("name") or "")
        is_iraas = _is_acei_name(name) or _is_arb_name(name) or _has_any(name, MRA)
        if is_iraas and not is_stop_action(nm):
            nm["action"] = "stop"
            nm["dose"] = "отмена (stop)"
            nm["rationale"] = (
                (nm.get("rationale") or "")
                + f" | Автокоррекция: K+={k_val} (≥{k_threshold}) день {trigger_day} → stop иРААС/АМКР."
            ).strip(" |")
            nm["safety_override"] = "HYPERK_FORCE_STOP"
            changed = True
        elif is_iraas and is_stop_action(nm):
            # нормализуем хедж «отмена или снижение»
            dose = str(nm.get("dose") or "")
            if re.search(r"или\s+снижен|снижен.*или", dose, re.I) or "reduce" in str(
                nm.get("action") or ""
            ).lower():
                nm["action"] = "stop"
                nm["dose"] = "отмена (stop)"
                nm["safety_override"] = "HYPERK_FORCE_STOP"
                changed = True
        meds.append(nm)
    out["medications"] = meds
    if changed:
        prev = list(out.get("safety_overrides") or [])
        out["safety_overrides"] = prev + [
            f"HYPERK_FORCE_STOP day={trigger_day} K+={k_val}"
        ]
        changes = list(out.get("changes") or [])
        changes.append(
            f"Принудительная отмена иРААС/АМКР при K+={k_val} (день {trigger_day})."
        )
        out["changes"] = changes
    return out


def active_med_names(plan: dict[str, Any] | None) -> list[str]:
    """Имена активных (не stop) препаратов."""
    names: list[str] = []
    if not plan:
        return names
    for m in plan.get("medications") or []:
        if isinstance(m, dict):
            if is_stop_action(m):
                continue
            names.append(f"{m.get('name', '')} {m.get('dose', '')}")
        else:
            names.append(str(m))
    return names
