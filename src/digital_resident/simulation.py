from __future__ import annotations

from typing import Any


def _meds_blob(plan_meds: list[str] | None) -> str:
    return " ".join(plan_meds or []).lower()


def _has_iraas(plan_meds: list[str] | None) -> bool:
    blob = _meds_blob(plan_meds)
    acei = any(
        x in blob
        for x in (
            "периндоприл",
            "эналаприл",
            "лизиноприл",
            "рамиприл",
            "иапф",
            "acei",
        )
    )
    arb = any(
        x in blob
        for x in ("валсартан", "лозартан", "телмисартан", "кандесартан", "сартан", "бра")
    )
    # stopped meds still appear in snapshot text — treat explicit stop as inactive
    if "отмена (stop)" in blob or "action=stop" in blob:
        # if only stopped iraas left, detect crude: count stop near names
        if "отмена" in blob and not any(
            drug in blob and "отмена" not in blob[max(0, blob.find(drug) - 10) : blob.find(drug) + 40]
            for drug in ("периндоприл", "эналаприл", "валсартан", "лозартан")
        ):
            pass
    mra = "спиронолактон" in blob or "эплеренон" in blob
    return acei or arb or mra


def _active_iraas(plan_meds: list[str] | None) -> bool:
    """Грубая эвристика: есть иРААС/АМКР и нет маркера отмены рядом."""
    items = plan_meds or []
    active = False
    for raw in items:
        t = (raw or "").lower()
        if any(x in t for x in ("отмена", "stop", "hold")):
            continue
        if any(
            x in t
            for x in (
                "периндоприл",
                "эналаприл",
                "лизиноприл",
                "рамиприл",
                "иапф",
                "валсартан",
                "лозартан",
                "телмисартан",
                "кандесартан",
                "сартан",
                "спиронолактон",
            )
        ):
            active = True
    return active


def simulate_trajectory(
    scenario: str,
    patient: dict[str, Any],
    plan_meds: list[str] | None = None,
    days: list[int] | None = None,
) -> list[dict[str, Any]]:
    """Детерминированные контрольные точки (каждый день госпитализации).

    Учитывает грубо состав plan_meds: активный иРААС ускоряет рост K+ при ХБП
    и нужен для триггера hyperkalemia_day3.
    """
    stay = max(2, min(60, int(patient.get("ward_stay_days") or 14)))
    days = days or list(range(1, stay + 1))
    labs0 = dict(patient.get("labs_day0") or {})
    bp0 = patient.get("bp_office", "150/95")
    try:
        sbp0, dbp0 = [int(x) for x in bp0.replace(" ", "").split("/")]
    except Exception:
        sbp0, dbp0 = 150, 95

    iraas_on = _active_iraas(plan_meds)
    # для сценария осложнения без meds в snapshot — сохраняем демо-поведение ТЗ
    if scenario == "hyperkalemia_day3" and not (plan_meds or []):
        iraas_on = True

    points: list[dict[str, Any]] = []
    for d in days:
        labs = dict(labs0)
        sbp, dbp = sbp0, dbp0
        events: list[str] = []
        flags: list[str] = []

        if scenario == "baseline":
            progress_d = d - 1
            sbp = sbp0 - min(progress_d * 2, 28)
            dbp = dbp0 - min(progress_d, 16)
            k_slope = 0.03 if iraas_on else 0.01
            labs["k_mmol_l"] = round(labs0.get("k_mmol_l", 4.2) + k_slope * progress_d, 2)
            labs["creatinine_umol_l"] = labs0.get("creatinine_umol_l", 88) + (1 if d >= 3 else 0) + (
                1 if d >= 7 else 0
            )
            labs["egfr"] = max(85, labs0.get("egfr", 92) - (1 if d >= 3 else 0) - (1 if d >= 7 else 0))
            if d == 1:
                events.append("Старт терапии по КР (иРААС + АК/диуретик).")
            elif d < 3:
                events.append("Ежедневный контроль АД; переносимость оценивается.")
            elif d < 7:
                events.append("АД снижается, переносимость хорошая.")
            elif d < stay:
                events.append("Приближение к целевому АД.")
            else:
                events.append("Стабилизация на целевых значениях.")
            if iraas_on and d == 1:
                flags.append("iraas_active")

        elif scenario == "comorbid_ckd":
            progress_d = d - 1
            sbp = sbp0 - min(progress_d * 1.5, 18)
            dbp = dbp0 - min(0.7 * progress_d, 8)
            # иРААС при ХБП → быстрее растёт K+
            k_slope = 0.06 if iraas_on else 0.02
            labs["k_mmol_l"] = round(min(5.4, labs0.get("k_mmol_l", 4.9) + k_slope * progress_d), 2)
            labs["creatinine_umol_l"] = labs0.get("creatinine_umol_l", 148) + max(0, d - 2)
            labs["egfr"] = max(30, labs0.get("egfr", 38) - max(0, (d - 2) // 2))
            if d == 1:
                events.append("Учёт ХБП и аллергии на иАПФ при выборе схемы.")
                flags.append("need_gfr_before_nephrotoxic")
                flags.append("prefer_arb_over_acei")
                if not patient.get("consent_invasive", True):
                    flags.append("missing_consent")
                if iraas_on:
                    flags.append("iraas_active")
            elif d < 3:
                events.append("Ежедневный контроль K+ и рСКФ после старта иРААС.")
            elif d == 3:
                events.append("Контроль K+ и рСКФ после старта иРААС.")
                if labs["k_mmol_l"] >= 5.0:
                    flags.append("rising_potassium")
            else:
                events.append("Медленная титрация, акцент на безопасность.")
            blob = _meds_blob(plan_meds)
            if any(x in blob for x in ("периндоприл", "эналаприл", "иапф")) and "отмена" not in blob:
                if d == 1:
                    flags.append("acei_despite_risk")

        elif scenario == "hyperkalemia_day3":
            if d < 3:
                progress_d = d - 1
                sbp = sbp0 - progress_d * 2
                dbp = dbp0 - progress_d
                if iraas_on:
                    labs["k_mmol_l"] = round(labs0.get("k_mmol_l", 4.6) + 0.15 * progress_d, 2)
                events.append("Старт стандартной комбинации; ежедневный контроль АД и электролитов.")
            elif d == 3:
                sbp = sbp0 - 8
                dbp = dbp0 - 4
                if iraas_on:
                    labs["k_mmol_l"] = 5.7
                    labs["creatinine_umol_l"] = labs0.get("creatinine_umol_l", 118) + 35
                    labs["egfr"] = max(28, labs0.get("egfr", 52) - 18)
                    events.append(
                        "Осложнение: гиперкалиемия K+=5.7 и снижение рСКФ на фоне иРААС — триггер пересмотра."
                    )
                    flags.extend(
                        [
                            "hyperkalemia",
                            "egfr_drop",
                            "recalculate_plan",
                            "hold_or_adjust_iraas",
                        ]
                    )
                else:
                    # без иРААС тяжёлой hyperK нет — логика завязана на терапию
                    labs["k_mmol_l"] = round(min(5.0, labs0.get("k_mmol_l", 4.6) + 0.2), 2)
                    events.append("Без активного иРААС гиперкалиемия ≥5.5 не развилась.")
                    flags.append("no_iraas_no_severe_hyperk")
            else:
                progress = min(1.0, (d - 3) / max(1, stay - 3))
                sbp = round(sbp0 - 8 - 10 * progress)
                dbp = round(dbp0 - 4 - 6 * progress)
                if iraas_on:
                    labs["k_mmol_l"] = round(5.7 - 0.9 * progress, 2)
                    labs["creatinine_umol_l"] = labs0.get("creatinine_umol_l", 118) + round(
                        35 - 25 * progress
                    )
                    labs["egfr"] = round(max(28, labs0.get("egfr", 52) - 18) + 17 * progress, 1)
                    events.append("После коррекции: K+ и рСКФ стабилизируются, АД контролируется.")
                    flags.append("post_correction")
                else:
                    labs["k_mmol_l"] = round(labs0.get("k_mmol_l", 4.6) + 0.05, 2)
                    events.append("Стабильное течение без отмены иРААС.")
        else:
            events.append("Неизвестный сценарий — нейтральная динамика.")

        points.append(
            {
                "day": d,
                "bp": f"{int(sbp)}/{int(dbp)}",
                "labs": labs,
                "events": events,
                "flags": flags,
                "plan_meds_snapshot": plan_meds or [],
                "iraas_active": iraas_on,
            }
        )
    return points


def needs_replan(points: list[dict[str, Any]]) -> bool:
    return any("recalculate_plan" in (p.get("flags") or []) for p in points)
