from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from digital_resident.config import settings


def patients_dir() -> Path:
    d = settings()["root"] / "data" / "patients"
    d.mkdir(parents=True, exist_ok=True)
    return d


def cohort_path() -> Path:
    return patients_dir() / "cohort.json"


def results_dir() -> Path:
    d = settings()["root"] / "data" / "patient_runs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize_sex(raw: Any) -> str:
    """Хранение: M / F. Принимает M/F/М/Ж/муж/жен."""
    s = str(raw or "M").strip().lower()
    if s in {"f", "ж", "female", "жен", "женский", "woman"}:
        return "F"
    return "M"


def format_sex_ru(sex: Any) -> str:
    """Отображение в UI: М или Ж."""
    return "Ж" if _normalize_sex(sex) == "F" else "М"


def infer_scenario(patient: dict[str, Any]) -> str:
    """Выбор сценария симуляции по данным пациента."""
    forced = (patient.get("scenario") or "").strip()
    if forced in {"baseline", "comorbid_ckd", "hyperkalemia_day3"}:
        return forced
    labs = patient.get("labs_day0") or {}
    egfr = float(labs.get("egfr") or 999)
    k = float(labs.get("k_mmol_l") or 0)
    text = " ".join(
        [
            " ".join(patient.get("comorbidities") or []),
            " ".join(patient.get("allergies") or []),
            patient.get("notes") or "",
            patient.get("diagnosis") or "",
        ]
    ).lower()
    if patient.get("force_complication") or "осложнен" in text or "день 3" in text:
        return "hyperkalemia_day3"
    if egfr < 45 or "хбп" in text or "ангио" in text or k >= 4.8:
        return "comorbid_ckd"
    return "baseline"


SCENARIO_LABELS: dict[str, str] = {
    "baseline": "Типичное течение АГ",
    "comorbid_ckd": "Коморбидность с ХБП",
    "hyperkalemia_day3": "Осложнение: рост калия на 2–4 день",
    "auto": "Автоматически по данным пациента",
}


def scenario_label(code: str | None) -> str:
    """Человекочитаемое название сценария для UI."""
    c = (code or "").strip()
    if not c:
        return "—"
    return SCENARIO_LABELS.get(c, c)


def normalize_patient(raw: dict[str, Any]) -> dict[str, Any]:
    labs = dict(raw.get("labs_day0") or {})
    for key, default in [
        ("creatinine_umol_l", 90),
        ("egfr", 90),
        ("k_mmol_l", 4.2),
        ("na_mmol_l", 140),
        ("glucose_mmol_l", 5.5),
        ("alt_u_l", 25),
        ("hb_g_l", 140),
        ("ldl_mmol_l", 3.2),
    ]:
        labs.setdefault(key, default)

    exams = raw.get("examinations") or raw.get("exams") or []
    notes_list = raw.get("health_notes") or []
    if isinstance(raw.get("notes"), str) and raw["notes"] and not notes_list:
        notes_list = [{"date": "day1", "text": raw["notes"]}]

    pid = raw.get("synthetic_id") or f"SYN-AG-{uuid4().hex[:6].upper()}"
    patient = {
        "synthetic_id": pid,
        "full_name": raw.get("full_name") or f"Пациент {pid}",
        "age": int(raw.get("age") or 55),
        "sex": _normalize_sex(raw.get("sex")),
        "diagnosis": raw.get("diagnosis") or "Артериальная гипертензия",
        "icd10": raw.get("icd10") or "I10",
        "bp_office": raw.get("bp_office") or "150/95",
        "hr": int(raw.get("hr") or 75),
        "weight_kg": float(raw.get("weight_kg") or 80),
        "height_cm": float(raw.get("height_cm") or 170),
        "allergies": list(raw.get("allergies") or []),
        "comorbidities": list(raw.get("comorbidities") or []),
        "current_meds": list(raw.get("current_meds") or []),
        "labs_day0": labs,
        "examinations": list(exams),
        "health_notes": list(notes_list),
        "notes": raw.get("notes")
        or "\n".join(n.get("text", "") for n in notes_list if isinstance(n, dict)),
        "consent_invasive": bool(raw.get("consent_invasive", True)),
        "scenario": raw.get("scenario") or "",
        "force_complication": bool(raw.get("force_complication", False)),
        "created_at": raw.get("created_at") or _now(),
        "updated_at": _now(),
        "source": raw.get("source") or "demo",
        "ward_stay_days": int(raw.get("ward_stay_days") or 14),
        "ward_history": list(raw.get("ward_history") or []),
    }
    patient["ward_stay_days"] = max(2, min(60, int(patient["ward_stay_days"] or 14)))
    patient["scenario"] = infer_scenario(patient)
    # Стационар: история N суток с ежедневными осмотрами (если не передана)
    if not patient["ward_history"]:
        if raw.get("skip_ward_history"):
            patient["ward_history"] = []
        else:
            patient["ward_history"] = build_ward_history(patient)
    else:
        patient["ward_history"] = [normalize_ward_entry(e) for e in patient["ward_history"]]
        # Миграция со старого шага «через день» → каждый день
        if _ward_needs_daily_upgrade(patient["ward_history"], patient["ward_stay_days"]):
            patient["ward_history"] = build_ward_history(patient)
    # day0 в шапке + синхронизация с колонкой «Заметки» стационара
    return sync_state_notes(patient)


_WARD_DAY_NOTE_RE = re.compile(r"^day(-?\d+)$", re.IGNORECASE)
_AUTO_WARD_NOTE_STARTS = (
    # устаревшие шаблоны средних дней (до раздельной логики осмотр/заметки)
    "Коррекция доз по АД",
    "Продолжаем стационарный режим",
    "План амбулаторного продолжения терапии",
)
# устаревшие/путающие преданамнезные шаблоны
_DROP_NOTE_TEXT_SUBSTR = (
    "кофе 3 чашки",
    "соль не ограничивает, кофе",
)
# day-30 с головными болями — старый сид; переносим на day-7
_REMAP_NOTE_DATES = {
    ("day-30", "головные боли по утрам"): "day-7",
}


def ward_day_note_date(day: int) -> str:
    return f"day{int(day)}"


def is_ward_day_note_date(date_str: str) -> bool:
    """True для дней стационара day1..dayN (не преданамнез day-7 и не устаревший day0)."""
    m = _WARD_DAY_NOTE_RE.match(str(date_str or "").strip())
    if not m:
        return False
    return int(m.group(1)) >= 1


def _parse_note_day(date_str: str) -> int | None:
    m = _WARD_DAY_NOTE_RE.match(str(date_str or "").strip())
    return int(m.group(1)) if m else None


def _normalize_note_date(date_str: str) -> str:
    """Канон даты: day0→day1; day07→day7; одна метка на сутки."""
    d = str(date_str or "").strip() or "day1"
    if d.lower() == "day0":
        return "day1"
    n = _parse_note_day(d)
    if n is not None:
        return f"day{n}"
    return d


def _note_sort_key(date_str: str) -> tuple:
    """Сортировка от меньшего дня к большему: day-30 < day-14 < day1 < day14."""
    n = _parse_note_day(date_str)
    if n is not None:
        return (0, n)
    return (1, str(date_str or "").lower())


def format_note_day_label(date_str: str, *, stay_days: int | None = None) -> str:
    """Метка суток для UI: номер = день таблицы (без слова «День» в осмотре/заметках)."""
    raw = _normalize_note_date(str(date_str or "").strip())
    n = _parse_note_day(raw)
    if n is None:
        return raw or "—"
    stay = int(stay_days) if stay_days else None
    if n == 1:
        return "1 · поступление"
    if stay is not None and n >= stay:
        return f"{n} · выписка"
    return str(n)


def _is_auto_ward_note(text: str) -> bool:
    t = str(text or "").strip()
    return any(t.startswith(p) for p in _AUTO_WARD_NOTE_STARTS)


def _is_plan_ward_note(text: str) -> bool:
    t = str(text or "").strip()
    return t.startswith("Госпитализация на") or t.startswith("Выписка.")


def _clinical_admission_from_seed(synthetic_id: str) -> str:
    """Клиническая заметка поступления из DEMO_SEED (day1 / устаревший day0)."""
    sid = str(synthetic_id or "").strip()
    if not sid:
        return ""
    seed = next((p for p in DEMO_SEED if p.get("synthetic_id") == sid), None)
    if not seed:
        return ""
    parts: list[str] = []
    for n in seed.get("health_notes") or []:
        if not isinstance(n, dict):
            continue
        if _normalize_note_date(str(n.get("date") or "")) != "day1":
            continue
        t = str(n.get("text") or "").strip()
        if t and not _is_plan_ward_note(t):
            parts.append(t)
    return " ".join(parts)


def _should_drop_note_text(text: str) -> bool:
    low = str(text or "").lower()
    return any(s in low for s in _DROP_NOTE_TEXT_SUBSTR)

def scrub_auto_ward_notes(patient: dict[str, Any]) -> dict[str, Any]:
    """Убрать только устаревшие шаблонные заметки; актуальные дневные заметки не трогаем."""
    hist = list(patient.get("ward_history") or [])
    for e in hist:
        if _is_auto_ward_note(str(e.get("notes") or "")):
            e["notes"] = ""
    patient["ward_history"] = hist
    return patient


def dedupe_sort_health_notes(notes: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Одна запись на сутки (последний текст побеждает), сортировка по дню ↑."""
    by_date: dict[str, str] = {}
    for n in notes or []:
        if not isinstance(n, dict):
            continue
        text = str(n.get("text") or "").strip()
        date = _normalize_note_date(str(n.get("date") or "").strip() or "day1")
        if not text or _should_drop_note_text(text):
            continue
        low = text.lower()
        for (d0, needle), d1 in _REMAP_NOTE_DATES.items():
            if date.lower() == d0 and needle in low:
                date = d1
                break
        # не склеиваем — обновление дня перезаписывает заметку
        by_date[date] = text
    return [
        {"date": d, "text": by_date[d]}
        for d in sorted(by_date.keys(), key=_note_sort_key)
    ]


def sync_health_notes_from_ward(patient: dict[str, Any]) -> dict[str, Any]:
    """Собрать health_notes только из стационара (day1..N) + клиническая day1.

    Преданамнез day-N (например day-7) в шапку не выносится — день = номер строки таблицы.
    """
    patient = scrub_auto_ward_notes(patient)
    hist = patient.get("ward_history") or []
    existing = [n for n in (patient.get("health_notes") or []) if isinstance(n, dict)]

    existing_adm = ""
    for n in existing:
        text = str(n.get("text") or "").strip()
        date = _normalize_note_date(str(n.get("date") or "").strip() or "day1")
        if not text or _should_drop_note_text(text):
            continue
        day_n = _parse_note_day(date)
        # отрицательные «до поступления» отбрасываем
        if day_n is not None and day_n < 1:
            continue
        if date.lower() == "day1":
            if not _is_plan_ward_note(text) or not existing_adm:
                if not text.startswith("Жалобы на дискомфорт") and not text.startswith(
                    "Состояние при поступлении"
                ):
                    existing_adm = text

    from_ward: list[dict[str, str]] = []
    for e in sorted(hist, key=lambda x: int(x.get("day") or 0)):
        d = int(e.get("day") or 0)
        text = str(e.get("notes") or "").strip()
        if not text or _is_auto_ward_note(text):
            continue
        if d == 1:
            # шаблон «Госпитализация…» в таблице не затирает клиническую day1 в шапке
            if existing_adm and not _is_plan_ward_note(existing_adm):
                from_ward.append({"date": "day1", "text": existing_adm})
            elif not _is_plan_ward_note(text):
                from_ward.append({"date": "day1", "text": text})
            else:
                restored = _clinical_admission_from_seed(str(patient.get("synthetic_id") or ""))
                if restored:
                    from_ward.append({"date": "day1", "text": restored})
                else:
                    from_ward.append({"date": "day1", "text": text})
            continue
        from_ward.append({"date": ward_day_note_date(d), "text": text})

    if not any(n["date"].lower() == "day1" for n in from_ward):
        if existing_adm and not _is_plan_ward_note(existing_adm):
            from_ward.insert(0, {"date": "day1", "text": existing_adm})
        else:
            restored = _clinical_admission_from_seed(str(patient.get("synthetic_id") or ""))
            if restored:
                from_ward.insert(0, {"date": "day1", "text": restored})

    patient["health_notes"] = dedupe_sort_health_notes(from_ward)
    patient["notes"] = "\n".join(n["text"] for n in patient["health_notes"])
    return patient


def ensure_admission_note(patient: dict[str, Any]) -> dict[str, Any]:
    """Гарантировать заметку дня поступления (day1) в шапке и в ward day1."""
    default_text = "Поступление в стационар. Первичный осмотр, готов к терапии."
    notes = [n for n in (patient.get("health_notes") or []) if isinstance(n, dict)]
    day1 = next(
        (
            n
            for n in notes
            if _normalize_note_date(str(n.get("date") or "")) == "day1"
        ),
        None,
    )
    day1_text = str((day1 or {}).get("text") or "").strip()
    if not day1_text or _is_plan_ward_note(day1_text):
        day1_text = (
            _clinical_admission_from_seed(str(patient.get("synthetic_id") or "")) or default_text
        )
    notes = [
        n
        for n in notes
        if _normalize_note_date(str(n.get("date") or "")) != "day1"
    ]
    # day1 держим первым среди стационарных; преданамнез выше по списку оставим как был
    insert_at = 0
    for i, n in enumerate(notes):
        if is_ward_day_note_date(str(n.get("date") or "")):
            insert_at = i
            break
        insert_at = i + 1
    notes.insert(insert_at, {"date": "day1", "text": day1_text})
    patient["health_notes"] = notes

    hist = list(patient.get("ward_history") or [])
    for e in hist:
        if int(e.get("day") or -1) == 1:
            ward_note = str(e.get("notes") or "").strip()
            if not ward_note:
                # в таблицу — краткая клиническая, если колонка пуста
                e["notes"] = day1_text
            elif _is_plan_ward_note(ward_note):
                pass  # шаблон плана не затирает клиническую day1 в шапке
            # сгенерированная «Состояние при поступлении…» и ручные заметки
            # остаются в таблице; шапка держит клиническую day1_text
            break
    patient["ward_history"] = hist
    return patient


def sync_state_notes(patient: dict[str, Any]) -> dict[str, Any]:
    """day1 обязательно + health_notes ↔ ward.notes."""
    patient = ensure_admission_note(patient)
    return sync_health_notes_from_ward(patient)


WARD_DAYS = tuple(range(1, 15))  # 1..14 включительно, каждый день


def ward_days_for_stay(stay_days: int) -> list[int]:
    """Точки осмотра: каждый день от 1 до stay_days включительно (N суток = N записей)."""
    stay = max(2, min(60, int(stay_days or 14)))
    return list(range(1, stay + 1))


def _ward_needs_daily_upgrade(history: list[dict[str, Any]], stay_days: int) -> bool:
    """True, если история не совпадает с 1..N (в т.ч. старый формат 0..N или «через день»)."""
    if not history:
        return True
    stay = max(2, min(60, int(stay_days or 14)))
    days = sorted({int(e.get("day") or 0) for e in history})
    expected = list(range(1, stay + 1))
    return days != expected


def _parse_bp_pair(bp: str) -> tuple[float, float]:
    try:
        s, d = str(bp).replace(" ", "").split("/")
        return float(s), float(d)
    except Exception:
        return 150.0, 95.0


def normalize_ward_entry(raw: dict[str, Any]) -> dict[str, Any]:
    labs = dict(raw.get("labs") or {})
    for key, default in [
        ("k_mmol_l", 4.2),
        ("egfr", 90),
        ("creatinine_umol_l", 90),
        ("glucose_mmol_l", 5.5),
    ]:
        if key in raw and raw[key] is not None and key not in labs:
            labs[key] = raw[key]
        labs.setdefault(key, default)

    def _num(val: Any, default: float) -> float:
        try:
            if val is None:
                return float(default)
            f = float(val)
            if f != f:  # NaN
                return float(default)
            return f
        except Exception:
            return float(default)

    day_raw = raw.get("day")
    try:
        day = int(float(day_raw)) if day_raw is not None and str(day_raw) != "nan" else 1
    except Exception:
        day = 1

    return {
        "day": day,
        "label": raw.get("label")
        or (f"День {day} · поступление" if day == 1 else f"День {day}"),
        "bp": str(raw.get("bp") or "140/90"),
        "hr": int(_num(raw.get("hr"), 75)),
        "weight_kg": round(_num(raw.get("weight_kg"), 80), 1),
        "labs": {
            "k_mmol_l": round(_num(labs.get("k_mmol_l"), 4.2), 2),
            "egfr": round(_num(labs.get("egfr"), 90), 1),
            "creatinine_umol_l": round(_num(labs.get("creatinine_umol_l"), 90), 1),
            "glucose_mmol_l": round(_num(labs.get("glucose_mmol_l"), 5.5), 1),
        },
        "exam": str(raw.get("exam") or ""),
        "results": str(raw.get("results") or ""),
        "notes": str(raw.get("notes") or ""),
    }


def _ward_day_texts(
    *,
    day: int,
    stay: int,
    t: float,
    scenario: str,
    name: str,
    dx: str,
    comorbid: str,
    meds: str,
    sbp: int,
    dbp: int,
    hr: int,
    k: float,
    egfr: float,
    cr: float,
    glu: float,
    note_arc: str,
) -> tuple[str, str, str, str]:
    """Осмотр и заметки — разные тексты; без префиксов «День N» / «Состояние».

    Номер дня берётся из колонки «День» (номер строки), не из текста.
    Returns: (exam, results, notes, label)
    """
    bp = f"{int(sbp)}/{int(dbp)}"
    # уникальные акценты по суткам, чтобы соседние дни не копировали друг друга
    exam_focus = [
        "утренний обход, лёгкие без хрипов",
        "оценка отёков и диуреза",
        "переносимость АГТ, ортостаз",
        "невростатус без очага",
        "аускультация сердца, тоны ясные",
        "контроль периферических отёков",
        "самочувствие на фоне титрации",
        "проверка дневника АД с пациентом",
        "подготовка к контрольным анализам",
        "оценка достижения целевого АД",
        "обучение самоконтролю перед выпиской",
        "финальная проверка жалоб",
    ]
    note_focus = [
        "адаптация к режиму, жалобы умеренные",
        "переносимость схемы удовлетворительная",
        "головные боли реже, сон лучше",
        "соль ограничивает, приверженность хорошая",
        "отёков нет, активность обычная",
        "АД по дневнику снижается плавно",
        "понимает схему приёма препаратов",
        "без новых жалоб, самочувствие ровное",
        "готовим план амбулаторного контроля",
        "целевое АД ближе, самочувствие стабильное",
        "знает, когда обратиться при ухудшении",
        "готов к выписке, рекомендации понятны",
    ]
    fi = (day - 2) % len(exam_focus)
    ni = (day - 2) % len(note_focus)

    if day == 1:
        exam = (
            f"Поступление. Первичный осмотр терапевта: {name}. "
            f"Диагноз: {dx}. Коморбидность: {comorbid}. "
            f"Объективно: АД {bp}, ЧСС {hr}, отёков нет/минимальные, лёгкие без хрипов."
        )
        results = (
            f"Лаборатория при поступлении: K+ {k}, рСКФ {egfr}, креатинин {cr}, глюкоза {glu}. "
            f"ЭКГ: синусовый ритм. Исходные препараты: {meds}."
        )
        notes = (
            f"Жалобы на дискомфорт/цефалгию. "
            f"Госпитализация на {stay} сут, старт титрации АГТ. {note_arc}"
        )
        return exam, results, notes, "День 1 · поступление"

    if day >= stay:
        exam = (
            f"Осмотр перед выпиской: состояние стабильное, "
            f"АД {bp}, ЧСС {hr}. Рекомендации и лист назначений выданы."
        )
        results = (
            f"Итоговые показатели: АД {bp}, ЧСС {hr}, K+ {k}, рСКФ {egfr}, "
            f"креатинин {cr}, глюкоза {glu}. Амбулаторный контроль через 7–14 дней."
        )
        notes = (
            "К выписке удовлетворительное. "
            "Продолжить назначенную схему, самоконтроль АД, мониторинг K+/рСКФ."
        )
        return exam, results, notes, f"День {day} · выписка"

    if scenario == "hyperkalemia_day3" and day == 3:
        exam = (
            f"Обход: нарастание слабости, парестезии неяркие. "
            f"АД {bp}, ЧСС {hr}. Акцент на электролиты и рСКФ."
        )
        results = (
            f"Тревожные labs: K+ {k}, рСКФ {egfr}, креатинин {cr}. "
            "Показан пересмотр иРААС / коррекция доз."
        )
        notes = (
            f"Ухудшение на фоне роста K+ ({k}). "
            "Предупреждён о симптомах гиперкалиемии, усилен мониторинг."
        )
        return exam, results, notes, f"День {day}"

    if scenario == "hyperkalemia_day3" and day > 3:
        exam = (
            f"После коррекции схемы: {exam_focus[fi]}. АД {bp}, ЧСС {hr}, отёков нет."
        )
        results = f"Контроль: K+ {k}, рСКФ {egfr}, креатинин {cr}. Тенденция к стабилизации."
        notes = (
            f"{note_focus[ni].capitalize()}. "
            f"После коррекции иРААС АД по дневнику около {bp}."
        )
        return exam, results, notes, f"День {day}"

    if scenario == "comorbid_ckd":
        exam = (
            f"Обход (ХБП): {exam_focus[fi]}. АД {bp}, ЧСС {hr}."
        )
        if t < 0.35:
            results = f"Контроль нефробезопасности: K+ {k}, рСКФ {egfr}, креатинин {cr}."
            notes = (
                f"{note_focus[ni].capitalize()}. "
                f"Обучен самоконтролю АД; акцент на K+/рСКФ. АД {bp}. {note_arc}"
            )
        elif t < 0.65:
            results = f"СМАД/дневник: снижение АД. Labs: K+ {k}, рСКФ {egfr}."
            notes = (
                f"{note_focus[ni].capitalize()}. "
                f"Соблюдает ограничение соли, отёки не нарастают. АД ~{bp}."
            )
        else:
            results = f"Контроль: K+ {k}, креатинин {cr}, рСКФ {egfr}, глюкоза {glu}."
            notes = (
                f"{note_focus[ni].capitalize()}. "
                f"Понимает схему и контрольные точки K+/рСКФ. АД сегодня {bp}."
            )
        return exam, results, notes, f"День {day}"

    # baseline
    exam = f"{exam_focus[fi].capitalize()}. АД {bp}, ЧСС {hr}."
    if t < 0.35:
        results = (
            f"Ежедневный контроль АД/ЧСС. Labs: K+ {k}, рСКФ {egfr}. "
            "ЭКГ/ЭхоКГ по показаниям."
        )
        notes = (
            f"{note_focus[ni].capitalize()}. "
            f"Фиксированная комбинация; АД на обходе {bp}. {note_arc}"
        )
    elif t < 0.65:
        results = f"Дневник АД — тенденция к снижению. Labs: K+ {k}, рСКФ {egfr}."
        notes = (
            f"{note_focus[ni].capitalize()}. "
            f"Приверженность терапии хорошая; АД ~{bp}."
        )
    else:
        results = f"Контрольные анализы: K+ {k}, креатинин {cr}, рСКФ {egfr}, глюкоза {glu}."
        notes = (
            f"{note_focus[ni].capitalize()}. "
            f"Знает целевое АД и план амбулаторного контроля. АД {bp}."
        )
    return exam, results, notes, f"День {day}"


def build_ward_history(
    patient: dict[str, Any],
    stay_days: int | None = None,
) -> list[dict[str, Any]]:
    """Синтетическая стационарная динамика: N суток; осмотр и заметки различны каждый день."""
    stay = int(stay_days if stay_days is not None else (patient.get("ward_stay_days") or 14))
    stay = max(2, min(60, stay))
    days = ward_days_for_stay(stay)

    labs0 = dict(patient.get("labs_day0") or {})
    sbp0, dbp0 = _parse_bp_pair(patient.get("bp_office") or "150/95")
    hr0 = int(patient.get("hr") or 75)
    w0 = float(patient.get("weight_kg") or 80)
    k0 = float(labs0.get("k_mmol_l") or 4.2)
    egfr0 = float(labs0.get("egfr") or 90)
    cr0 = float(labs0.get("creatinine_umol_l") or 90)
    glu0 = float(labs0.get("glucose_mmol_l") or 5.5)
    scenario = patient.get("scenario") or "baseline"
    name = patient.get("full_name") or "пациент"
    dx = patient.get("diagnosis") or "АГ"
    comorbid = ", ".join(patient.get("comorbidities") or []) or "без значимой коморбидности"
    meds = ", ".join(patient.get("current_meds") or []) or "терапия не начата"

    history: list[dict[str, Any]] = []
    for day in days:
        t = (day - 1) / float(max(1, stay - 1))
        if scenario == "comorbid_ckd":
            sbp = round(sbp0 - 18 * t)
            dbp = round(dbp0 - 8 * t)
            k = round(k0 + 0.15 * t, 2)
            egfr = round(egfr0 - 3 * t, 1)
            cr = round(cr0 + 8 * t, 1)
            note_arc = "Контроль K+/рСКФ; избегаем тиазида и иАПФ при ангиоотёке."
        elif scenario == "hyperkalemia_day3":
            early = stay * 0.15
            mid = stay * 0.35
            bump = 1.1 if early <= day <= mid else (0.3 if day > mid else 0.0)
            sbp = round(sbp0 - 12 * t)
            dbp = round(dbp0 - 6 * t)
            k = round(min(5.9, k0 + bump), 2)
            egfr = round(egfr0 - (12 if day >= early else 0) - 4 * t, 1)
            cr = round(cr0 + (25 if day >= early else 0) + 6 * t, 1)
            note_arc = "Риск гиперкалиемии — коррекция иРААС при росте K+."
        else:
            sbp = round(sbp0 - 22 * t)
            dbp = round(dbp0 - 10 * t)
            k = round(k0 + 0.05 * t, 2)
            egfr = round(egfr0 - 1 * t, 1)
            cr = round(cr0 + 2 * t, 1)
            note_arc = "Фиксированная комбинация, целевое АД."

        hr = max(58, round(hr0 - 6 * t + (2 if day % 4 == 0 else 0)))
        weight = round(w0 - 0.4 * t, 1)
        glu = round(glu0 - 0.2 * t, 1)

        exam, results, notes, label = _ward_day_texts(
            day=day,
            stay=stay,
            t=t,
            scenario=scenario,
            name=name,
            dx=dx,
            comorbid=comorbid,
            meds=meds,
            sbp=int(sbp),
            dbp=int(dbp),
            hr=int(hr),
            k=k,
            egfr=egfr,
            cr=cr,
            glu=glu,
            note_arc=note_arc,
        )
        history.append(
            normalize_ward_entry(
                {
                    "day": day,
                    "label": label,
                    "bp": f"{int(sbp)}/{int(dbp)}",
                    "hr": hr,
                    "weight_kg": weight,
                    "labs": {
                        "k_mmol_l": k,
                        "egfr": egfr,
                        "creatinine_umol_l": cr,
                        "glucose_mmol_l": glu,
                    },
                    "exam": exam,
                    "results": results,
                    "notes": notes,
                }
            )
        )
    return history


def ward_history_to_rows(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for e in history or []:
        e = normalize_ward_entry(e)
        labs = e.get("labs") or {}
        rows.append(
            {
                "День": e["day"],
                "АД": e["bp"],
                "ЧСС": e["hr"],
                "Вес": e["weight_kg"],
                "K+": labs.get("k_mmol_l"),
                "рСКФ": labs.get("egfr"),
                "Креатинин": labs.get("creatinine_umol_l"),
                "Глюкоза": labs.get("glucose_mmol_l"),
                "Осмотр": e.get("exam") or "",
                "Результаты": e.get("results") or "",
                "Заметки": e.get("notes") or "",
            }
        )
    return rows


def rows_to_ward_history(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def _blank(val: Any) -> bool:
        if val is None:
            return True
        try:
            if isinstance(val, float) and math.isnan(val):
                return True
        except Exception:
            pass
        s = str(val).strip().lower()
        return s in {"", "nan", "none", "nat"}

    out: list[dict[str, Any]] = []
    for r in rows or []:
        if r is None:
            continue
        day_val = r.get("День") if "День" in r else r.get("day")
        has_content = any(
            not _blank(r.get(k))
            for k in ("АД", "Осмотр", "Результаты", "Заметки", "ЧСС", "Вес", "K+", "рСКФ", "bp", "exam")
        )
        if _blank(day_val) and not has_content:
            continue
        if _blank(day_val):
            day_val = 1
        out.append(
            normalize_ward_entry(
                {
                    "day": day_val,
                    "bp": r.get("АД") or r.get("bp"),
                    "hr": r.get("ЧСС") if not _blank(r.get("ЧСС")) else r.get("hr"),
                    "weight_kg": r.get("Вес") if not _blank(r.get("Вес")) else r.get("weight_kg"),
                    "k_mmol_l": r.get("K+") if not _blank(r.get("K+")) else r.get("k_mmol_l"),
                    "egfr": r.get("рСКФ") if not _blank(r.get("рСКФ")) else r.get("egfr"),
                    "creatinine_umol_l": r.get("Креатинин")
                    if not _blank(r.get("Креатинин"))
                    else r.get("creatinine_umol_l"),
                    "glucose_mmol_l": r.get("Глюкоза")
                    if not _blank(r.get("Глюкоза"))
                    else r.get("glucose_mmol_l"),
                    "exam": "" if _blank(r.get("Осмотр")) else (r.get("Осмотр") or r.get("exam") or ""),
                    "results": ""
                    if _blank(r.get("Результаты"))
                    else (r.get("Результаты") or r.get("results") or ""),
                    "notes": "" if _blank(r.get("Заметки")) else (r.get("Заметки") or r.get("notes") or ""),
                }
            )
        )
    out.sort(key=lambda x: x["day"])
    return out


DEMO_SEED: list[dict[str, Any]] = [
    {
        "synthetic_id": "SYN-AG-001",
        "full_name": "Иванов Алексей Петрович",
        "age": 54,
        "sex": "M",
        "diagnosis": "Артериальная гипертензия, 2 степень, риск 3",
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
            "hb_g_l": 146,
            "ldl_mmol_l": 3.8,
        },
        "examinations": [
            {"name": "ЭКГ", "result": "Синусовый ритм, без ишемии", "date": "day0"},
            {"name": "ЭхоКГ", "result": "ФВ 58%, лёгкая ГЛЖ", "date": "day0"},
            {"name": "СМАД", "result": "Среднее дневное 154/96", "date": "day-7"},
        ],
        "health_notes": [
            {
                "date": "day1",
                "text": (
                    "Поступление. Курение отрицает. Готов к терапии. "
                    "Ранее головные боли по утрам 2–3 раза в неделю. "
                    "Семейный анамнез: отец — ИМ в 60 лет."
                ),
            },
        ],
        "consent_invasive": True,
        "scenario": "baseline",
        "source": "demo",
    },
    {
        "synthetic_id": "SYN-AG-002",
        "full_name": "Петрова Наталья Ивановна",
        "age": 68,
        "sex": "F",
        "diagnosis": "АГ 3 ст.; ХБП С3б А2",
        "icd10": "I12.9",
        "bp_office": "172/94",
        "hr": 72,
        "weight_kg": 71,
        "height_cm": 162,
        "allergies": ["Эналаприл — ангионевротический отёк"],
        "comorbidities": ["ХБП С3б", "Анемия лёгкой степени"],
        "current_meds": ["Амлодипин 5 мг"],
        "labs_day0": {
            "creatinine_umol_l": 148,
            "egfr": 38,
            "k_mmol_l": 4.9,
            "na_mmol_l": 138,
            "glucose_mmol_l": 5.9,
            "alt_u_l": 22,
            "hb_g_l": 112,
            "ldl_mmol_l": 2.9,
        },
        "examinations": [
            {"name": "УЗИ почек", "result": "Диффузные изменения паренхимы, размеры ↓", "date": "day-10"},
            {"name": "ЭКГ", "result": "Синусовый ритм, признаки ГЛЖ", "date": "day0"},
            {"name": "ОАМ", "result": "Микроальбуминурия", "date": "day0"},
        ],
        "health_notes": [
            {"date": "day-60", "text": "Отёк лица на эналаприл 2 года назад — повторно не назначать иАПФ."},
            {"date": "day-20", "text": "Отёки голеней к вечеру, диурез сохранён."},
            {"date": "day-5", "text": "Нефролог: рСКФ 38, целевое АД <140/80 затем к 130."},
            {"date": "day1", "text": "Согласие на инвазивные процедуры НЕ подписано."},
            {"date": "day1", "text": "Жалобы: слабость, шум в ушах при АД >170."},
        ],
        "consent_invasive": False,
        "scenario": "comorbid_ckd",
        "source": "demo",
    },
    {
        "synthetic_id": "SYN-AG-003",
        "full_name": "Сидоров Виктор Константинович",
        "age": 61,
        "sex": "M",
        "diagnosis": "АГ 2 ст.; ХБП С3а",
        "icd10": "I12.9",
        "bp_office": "164/100",
        "hr": 80,
        "weight_kg": 90,
        "height_cm": 178,
        "allergies": [],
        "comorbidities": ["ХБП С3а", "Ожирение 1 ст."],
        "current_meds": [],
        "labs_day0": {
            "creatinine_umol_l": 118,
            "egfr": 52,
            "k_mmol_l": 4.6,
            "na_mmol_l": 141,
            "glucose_mmol_l": 6.1,
            "alt_u_l": 35,
            "hb_g_l": 139,
            "ldl_mmol_l": 3.5,
        },
        "examinations": [
            {"name": "ЭхоКГ", "result": "ФВ 55%, ГЛЖ умеренная", "date": "day0"},
            {"name": "Биохимия", "result": "Старт иРААС — контроль K+/СКФ через 3 дня", "date": "day0"},
        ],
        "health_notes": [
            {"date": "day-14", "text": "ИМТ 28.4, одышка при нагрузке."},
            {"date": "day1", "text": "Планируется старт двойной терапии; риск гиперкалиемии."},
            {"date": "day1", "text": "Симуляция: на день 3 ожидается осложнение (рост K+)."},
        ],
        "consent_invasive": True,
        "scenario": "hyperkalemia_day3",
        "force_complication": True,
        "source": "demo",
    },
    {
        "synthetic_id": "SYN-AG-004",
        "full_name": "Козлова Елена Михайловна",
        "age": 47,
        "sex": "F",
        "diagnosis": "АГ 1 ст., риск 2",
        "icd10": "I10",
        "bp_office": "148/92",
        "hr": 74,
        "weight_kg": 64,
        "height_cm": 165,
        "allergies": ["Пенициллин — сыпь"],
        "comorbidities": ["Мигрень"],
        "current_meds": [],
        "labs_day0": {
            "creatinine_umol_l": 72,
            "egfr": 98,
            "k_mmol_l": 4.0,
            "glucose_mmol_l": 5.1,
            "ldl_mmol_l": 3.1,
            "hb_g_l": 132,
        },
        "examinations": [
            {"name": "СМАД", "result": "Среднее 142/88, ночной dip есть", "date": "day-3"},
            {"name": "ЭКГ", "result": "Норма", "date": "day0"},
        ],
        "health_notes": [
            {"date": "day-21", "text": "Стресс на работе, АД повышается к вечеру."},
            {"date": "day-7", "text": "Ограничила соль, АД чуть снизилось."},
            {"date": "day1", "text": "Хочет начать терапию с минимальных доз."},
            {"date": "day1", "text": "Беременность исключена, контрацепция."},
        ],
        "consent_invasive": True,
        "scenario": "baseline",
    },
    {
        "synthetic_id": "SYN-AG-005",
        "full_name": "Морозов Иван Сергеевич",
        "age": 72,
        "sex": "M",
        "diagnosis": "АГ 3 ст.; ИБС; ХБП С3а",
        "icd10": "I11.9",
        "bp_office": "168/86",
        "hr": 66,
        "weight_kg": 78,
        "height_cm": 174,
        "allergies": [],
        "comorbidities": ["ИБС, стенокардия 2 ФК", "ХБП С3а", "Сахарный диабет 2 типа"],
        "current_meds": ["Бисопролол 5 мг", "Аторвастатин 20 мг", "Метформин 1000 мг"],
        "labs_day0": {
            "creatinine_umol_l": 125,
            "egfr": 48,
            "k_mmol_l": 4.7,
            "glucose_mmol_l": 7.8,
            "hb_g_l": 128,
            "ldl_mmol_l": 2.4,
        },
        "examinations": [
            {"name": "ЭКГ", "result": "Ритм синусовый, рубцовые изменения нижней стенки", "date": "day0"},
            {"name": "ЭхоКГ", "result": "ФВ 48%, гипокинез нижней стенки", "date": "day-5"},
            {"name": "HbA1c", "result": "7.4%", "date": "day-14"},
        ],
        "health_notes": [
            {"date": "day-40", "text": "Приступы стенокардии при ходьбе >300 м."},
            {"date": "day-10", "text": "Кардиолог: добавить иРААС, контроль K+."},
            {"date": "day1", "text": "Отёков нет, одышка при нагрузке."},
            {"date": "day1", "text": "Приверженность к статину хорошая."},
        ],
        "consent_invasive": True,
        "scenario": "comorbid_ckd",
    },
    {
        "synthetic_id": "SYN-AG-006",
        "full_name": "Новикова Татьяна Андреевна",
        "age": 59,
        "sex": "F",
        "diagnosis": "АГ 2 ст.; бронхиальная астма",
        "icd10": "I10",
        "bp_office": "156/94",
        "hr": 82,
        "weight_kg": 69,
        "height_cm": 160,
        "allergies": ["Аспирин — бронхоспазм"],
        "comorbidities": ["Бронхиальная астма среднетяжёлая"],
        "current_meds": ["Будесонид/формотерол ингал."],
        "labs_day0": {
            "creatinine_umol_l": 80,
            "egfr": 88,
            "k_mmol_l": 4.1,
            "glucose_mmol_l": 5.3,
            "hb_g_l": 136,
        },
        "examinations": [
            {"name": "Спирометрия", "result": "ОФВ1 68% после бронходилататора", "date": "day-20"},
            {"name": "ЭКГ", "result": "Синусовая тахикардия", "date": "day0"},
        ],
        "health_notes": [
            {"date": "day-30", "text": "Непереносимость НПВП/аспирина — бронхоспазм."},
            {"date": "day-12", "text": "Пульмонолог: ББ неселективные нежелательны."},
            {"date": "day1", "text": "Предпочтительны иРААС + АК; избегать неселективных ББ."},
            {"date": "day1", "text": "Обострений астмы за 6 мес не было."},
        ],
        "consent_invasive": True,
        "scenario": "baseline",
    },
    {
        "synthetic_id": "SYN-AG-007",
        "full_name": "Фёдоров Дмитрий Леонидович",
        "age": 65,
        "sex": "M",
        "diagnosis": "Резистентная АГ?; АГ 3 ст.; ХБП С3б",
        "icd10": "I12.9",
        "bp_office": "178/102",
        "hr": 70,
        "weight_kg": 95,
        "height_cm": 180,
        "allergies": [],
        "comorbidities": ["ХБП С3б", "Подагра"],
        "current_meds": ["Периндоприл 10 мг", "Амлодипин 10 мг", "Индапамид 1.5 мг"],
        "labs_day0": {
            "creatinine_umol_l": 155,
            "egfr": 36,
            "k_mmol_l": 4.8,
            "glucose_mmol_l": 5.8,
            "hb_g_l": 124,
            "ldl_mmol_l": 3.0,
        },
        "examinations": [
            {"name": "СМАД", "result": "Среднее 170/100 на тройной терапии", "date": "day-2"},
            {"name": "Калий", "result": "4.8 — на границе перед эскалацией", "date": "day0"},
        ],
        "health_notes": [
            {"date": "day-45", "text": "АД не достигает цели на тройной комбинации."},
            {"date": "day-15", "text": "Рассматривали спиронолактон — риск гиперкалиемии при СКФ 36."},
            {"date": "day1", "text": "Соль не ограничивает, ИМТ 29."},
            {"date": "day1", "text": "Нужен тщательный мониторинг K+/СКФ при усилении терапии."},
        ],
        "consent_invasive": True,
        "scenario": "comorbid_ckd",
    },
    {
        "synthetic_id": "SYN-AG-008",
        "full_name": "Белова Ольга Романовна",
        "age": 52,
        "sex": "F",
        "diagnosis": "АГ 2 ст.; язвенная болезнь в анамнезе",
        "icd10": "I10",
        "bp_office": "160/96",
        "hr": 76,
        "weight_kg": 70,
        "height_cm": 168,
        "allergies": [],
        "comorbidities": ["Язвенная болезнь ДПК (ремиссия)"],
        "current_meds": ["Омепразол 20 мг курсами"],
        "labs_day0": {
            "creatinine_umol_l": 78,
            "egfr": 95,
            "k_mmol_l": 4.3,
            "glucose_mmol_l": 5.2,
            "hb_g_l": 129,
        },
        "examinations": [
            {"name": "ФГДС", "result": "Рубцовая деформация луковицы ДПК, без активной язвы", "date": "day-90"},
            {"name": "ЭКГ", "result": "Норма", "date": "day0"},
        ],
        "health_notes": [
            {"date": "day-90", "text": "Обострение язвы год назад на фоне НПВП."},
            {"date": "day-20", "text": "Избегать НПВП; АГТ стандартная допустима."},
            {"date": "day1", "text": "Жалобы: тяжесть в эпигастрии при стрессе."},
            {"date": "day1", "text": "Согласие на инвазивные подписано."},
        ],
        "consent_invasive": True,
        "scenario": "baseline",
    },
    {
        "synthetic_id": "SYN-AG-009",
        "full_name": "Орлов Павел Георгиевич",
        "age": 70,
        "sex": "M",
        "diagnosis": "АГ 2 ст.; ХБП С4",
        "icd10": "I12.9",
        "bp_office": "166/88",
        "hr": 68,
        "weight_kg": 74,
        "height_cm": 172,
        "allergies": ["Лизиноприл — сухой кашель"],
        "comorbidities": ["ХБП С4", "Анемия"],
        "current_meds": ["Амлодипин 5 мг"],
        "labs_day0": {
            "creatinine_umol_l": 210,
            "egfr": 28,
            "k_mmol_l": 5.0,
            "glucose_mmol_l": 5.6,
            "hb_g_l": 108,
        },
        "examinations": [
            {"name": "УЗИ почек", "result": "Сморщенные почки", "date": "day-30"},
            {"name": "Консультация нефролога", "result": "Петлевые диуретики; иРААС с осторожностью", "date": "day-7"},
        ],
        "health_notes": [
            {"date": "day-60", "text": "Кашель на лизиноприл — смена класса на БРА под контролем."},
            {"date": "day-14", "text": "рСКФ 28 — тиазиды противопоказаны."},
            {"date": "day1", "text": "K+=5.0 — на старте иРААС высокий риск."},
            {"date": "day1", "text": "Согласие на инвазивные НЕ оформлено."},
        ],
        "consent_invasive": False,
        "scenario": "comorbid_ckd",
    },
    {
        "synthetic_id": "SYN-AG-010",
        "full_name": "Кузнецова Мария Владимировна",
        "age": 58,
        "sex": "F",
        "diagnosis": "АГ 2 ст.; ожирение; ОСАС?",
        "icd10": "I10",
        "bp_office": "162/98",
        "hr": 84,
        "weight_kg": 98,
        "height_cm": 164,
        "allergies": [],
        "comorbidities": ["Ожирение 2 ст.", "Подозрение на ОСАС"],
        "current_meds": [],
        "labs_day0": {
            "creatinine_umol_l": 85,
            "egfr": 82,
            "k_mmol_l": 4.4,
            "glucose_mmol_l": 6.4,
            "hb_g_l": 141,
            "ldl_mmol_l": 4.1,
        },
        "examinations": [
            {"name": "ЭКГ", "result": "Синусовая тахикардия", "date": "day0"},
            {"name": "Пульсоксиметрия ночная", "result": "Мин. SpO2 86% — направление на полисомнографию", "date": "day-5"},
        ],
        "health_notes": [
            {"date": "day-25", "text": "Храп, дневная сонливость."},
            {"date": "day-10", "text": "Диетолог: цель −5–10% массы тела."},
            {"date": "day1", "text": "Готова к старту фиксированной комбинации."},
            {"date": "day1", "text": "Просит объяснить целевое АД и мониторинг."},
        ],
        "consent_invasive": True,
        "scenario": "baseline",
    },
]


def seed_cohort(force: bool = False) -> list[dict[str, Any]]:
    path = cohort_path()
    if path.exists() and not force:
        return load_cohort()
    cohort = [normalize_patient(p) for p in DEMO_SEED]
    save_cohort(cohort)
    return cohort


def is_case_record(p: dict[str, Any]) -> bool:
    """Кейсы задания не должны попадать в список пациентов когорты."""
    sid = str(p.get("synthetic_id") or "")
    name = str(p.get("full_name") or "").strip().lower()
    if sid.startswith("CASE-"):
        return True
    if name.startswith("кейс"):
        return True
    if (p.get("source") or "") == "assignment_case":
        return True
    return False


def load_cohort() -> list[dict[str, Any]]:
    path = cohort_path()
    if not path.exists():
        return seed_cohort(force=True)
    data = json.loads(path.read_text(encoding="utf-8"))
    seed_by_id = {p["synthetic_id"]: p for p in DEMO_SEED}
    cohort: list[dict[str, Any]] = []
    dirty = False
    for raw in data:
        name = str(raw.get("full_name") or "").strip().lower()
        # кейсы задания / испорченные карточки «Кейс …» — восстановить из сида или выкинуть
        if is_case_record(raw) or name.startswith("кейс"):
            sid = str(raw.get("synthetic_id") or "")
            if sid in seed_by_id:
                cohort.append(normalize_patient(seed_by_id[sid]))
                dirty = True
            else:
                dirty = True  # CASE-* не держим в когорте
            continue
        norm = normalize_patient(raw)
        raw_days = [int(e.get("day") or 0) for e in (raw.get("ward_history") or [])]
        new_days = [int(e.get("day") or 0) for e in (norm.get("ward_history") or [])]
        raw_notes = [
            (str(n.get("date") or ""), str(n.get("text") or ""))
            for n in (raw.get("health_notes") or [])
            if isinstance(n, dict)
        ]
        new_notes = [
            (str(n.get("date") or ""), str(n.get("text") or ""))
            for n in (norm.get("health_notes") or [])
            if isinstance(n, dict)
        ]
        if (
            not (raw.get("ward_history") or [])
            or raw_days != new_days
            or raw_notes != new_notes
        ):
            dirty = True
        cohort.append(norm)
    if dirty or len(data) != len(cohort):
        save_cohort(cohort)
        for p in cohort:
            single = patients_dir() / f"{p['synthetic_id']}.json"
            single.write_text(json.dumps(p, ensure_ascii=False, indent=2), encoding="utf-8")
    return cohort


def save_cohort(patients: list[dict[str, Any]]) -> Path:
    path = cohort_path()
    # никогда не пишем кейсы задания в когорту
    clean = [normalize_patient(p) for p in patients if not is_case_record(p)]
    path.write_text(
        json.dumps(clean, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def get_patient(synthetic_id: str) -> dict[str, Any]:
    for p in load_cohort():
        if p["synthetic_id"] == synthetic_id:
            return p
    raise KeyError(f"Пациент не найден: {synthetic_id}")


def upsert_patient(raw: dict[str, Any]) -> dict[str, Any]:
    patient = normalize_patient(raw)
    # кейсы задания — не сохраняем в когорту пациентов
    if is_case_record(patient):
        return patient
    cohort = load_cohort()
    out = []
    replaced = False
    for p in cohort:
        if p["synthetic_id"] == patient["synthetic_id"]:
            out.append(patient)
            replaced = True
        else:
            out.append(p)
    if not replaced:
        out.append(patient)
    save_cohort(out)
    # also single-file copy
    single = patients_dir() / f"{patient['synthetic_id']}.json"
    single.write_text(json.dumps(patient, ensure_ascii=False, indent=2), encoding="utf-8")
    return patient


def delete_patient(synthetic_id: str) -> bool:
    """Удалить пациента из когорты и одиночного JSON-файла."""
    sid = (synthetic_id or "").strip()
    if not sid:
        return False
    cohort = load_cohort()
    new_cohort = [p for p in cohort if p.get("synthetic_id") != sid]
    if len(new_cohort) == len(cohort):
        return False
    save_cohort(new_cohort)
    single = patients_dir() / f"{sid}.json"
    if single.exists():
        single.unlink()
    return True


def list_patients() -> list[dict[str, str]]:
    return [
        {
            "synthetic_id": p["synthetic_id"],
            "full_name": p.get("full_name", ""),
            "diagnosis": p.get("diagnosis", ""),
            "scenario": p.get("scenario", ""),
            "age": str(p.get("age", "")),
        }
        for p in load_cohort()
    ]


def parse_list_field(text: str) -> list[str]:
    if not text or not str(text).strip():
        return []
    parts = re.split(r"[;\n]+", str(text))
    return [p.strip() for p in parts if p.strip()]
