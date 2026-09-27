from __future__ import annotations

from typing import Any

CASES: dict[str, dict[str, Any]] = {
    "baseline": {
        "id": "baseline",
        "title": "Кейс 1 — Baseline (типичное течение)",
        "description": (
            "Первичный приём: АГ 2 ст., без значимой коморбидности. "
            "Первая линия по КР, положительная динамика АД и лаборатории."
        ),
        "patient": {
            "synthetic_id": "CASE-AG-001",
            "age": 54,
            "sex": "M",
            "diagnosis": "Артериальная гипертензия, 2 степень, риск 3 (высокий)",
            "icd10": "I10",
            "bp_office": "158/98",
            "hr": 78,
            "weight_kg": 82,
            "height_cm": 176,
            "allergies": [],
            "comorbidities": ["Дислипидемия"],
            "current_meds": [],
            "labs_day0": {
                "creatinine_umol_l": 88,
                "egfr": 92,
                "k_mmol_l": 4.2,
                "na_mmol_l": 140,
                "glucose_mmol_l": 5.4,
                "alt_u_l": 28,
            },
            "consent_invasive": True,
            "notes": "Синтетический пациент. Курение отрицает.",
            "source": "assignment_case",
            "full_name": "Кейс 1 — Baseline",
        },
        "scenario": "baseline",
    },
    "comorbid": {
        "id": "comorbid",
        "title": "Кейс 2 — Коморбидность (ХБП / противопоказание)",
        "description": (
            "АГ + ХБП С3б (рСКФ ~38). Нужна модификация стандартной схемы: "
            "осторожность с тиазидами/спиронолактоном, контроль K+ и СКФ."
        ),
        "patient": {
            "synthetic_id": "CASE-AG-002",
            "age": 68,
            "sex": "F",
            "diagnosis": "Артериальная гипертензия, 3 степень; ХБП С3б А2",
            "icd10": "I12.9",
            "bp_office": "172/94",
            "hr": 72,
            "weight_kg": 71,
            "height_cm": 162,
            "allergies": ["Эналаприл — ангионевротический отёк (анамнез)"],
            "comorbidities": [
                "ХБП С3б (рСКФ 38 мл/мин/1,73 м²)",
                "Анемия лёгкой степени",
            ],
            "current_meds": ["Амлодипин 5 мг"],
            "labs_day0": {
                "creatinine_umol_l": 148,
                "egfr": 38,
                "k_mmol_l": 4.9,
                "na_mmol_l": 138,
                "glucose_mmol_l": 5.9,
                "alt_u_l": 22,
            },
            "consent_invasive": False,
            "notes": (
                "Синтетический пациент. Ангиооотёк на иАПФ — предпочтителен БРА. "
                "Информированное согласие на инвазивные процедуры НЕ подписано."
            ),
            "source": "assignment_case",
            "full_name": "Кейс 2 — Коморбидность",
        },
        "scenario": "comorbid_ckd",
    },
    "complication": {
        "id": "complication",
        "title": "Кейс 3 — Осложнение (реактивная динамика на день 3)",
        "description": (
            "Старт стандартной двойной терапии; на день 3 — гиперкалиемия и рост креатинина. "
            "Требуется пересчёт плана и срабатывание аудитора."
        ),
        "patient": {
            "synthetic_id": "CASE-AG-003",
            "age": 61,
            "sex": "M",
            "diagnosis": "Артериальная гипертензия, 2 степень; ХБП С3а",
            "icd10": "I12.9",
            "bp_office": "164/100",
            "hr": 80,
            "weight_kg": 90,
            "height_cm": 178,
            "allergies": [],
            "comorbidities": ["ХБП С3а (рСКФ 52)", "Ожирение 1 ст."],
            "current_meds": [],
            "labs_day0": {
                "creatinine_umol_l": 118,
                "egfr": 52,
                "k_mmol_l": 4.6,
                "na_mmol_l": 141,
                "glucose_mmol_l": 6.1,
                "alt_u_l": 35,
            },
            "consent_invasive": True,
            "notes": "Синтетический пациент. На день 3 скрипт симуляции даёт гиперкалиемию.",
            "source": "assignment_case",
            "full_name": "Кейс 3 — Осложнение",
        },
        "scenario": "hyperkalemia_day3",
    },
}


def list_cases() -> list[dict[str, str]]:
    return [{"id": c["id"], "title": c["title"], "description": c["description"]} for c in CASES.values()]


def get_case(case_id: str) -> dict[str, Any]:
    if case_id not in CASES:
        raise KeyError(f"Неизвестный кейс: {case_id}")
    return CASES[case_id]
