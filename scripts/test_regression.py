#!/usr/bin/env python3
"""Офлайн регрессия + интеграционные проверки (без LLM)."""
from __future__ import annotations

import re
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

PASS = 0
FAIL = 0
ERRORS: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  OK  {name}")
    else:
        FAIL += 1
        msg = f"FAIL {name}" + (f" — {detail}" if detail else "")
        ERRORS.append(msg)
        print(f"  {msg}")


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def test_ward_days() -> None:
    section("Ward days 1..N")
    from digital_resident.patients import (
        build_ward_history,
        ward_days_for_stay,
        load_cohort,
    )
    from digital_resident.simulation import simulate_trajectory

    check("14 сут → 14 дней", ward_days_for_stay(14) == list(range(1, 15)))
    check("6 сут → 6 дней", ward_days_for_stay(6) == list(range(1, 7)))

    p = {
        "full_name": "Test",
        "diagnosis": "АГ",
        "scenario": "baseline",
        "bp_office": "150/95",
        "hr": 75,
        "weight_kg": 80,
        "labs_day0": {"k_mmol_l": 4.2, "egfr": 90, "creatinine_umol_l": 90, "glucose_mmol_l": 5.5},
        "ward_stay_days": 14,
    }
    hist = build_ward_history(p, stay_days=14)
    days = [e["day"] for e in hist]
    check("build_ward days 1..14", days == list(range(1, 15)), str(days[:3]))
    check("каждый день exam", all(str(e.get("exam") or "").strip() for e in hist))
    check("каждый день notes", all(str(e.get("notes") or "").strip() for e in hist))
    check(
        "exam ≠ notes",
        all(e["exam"].strip() != e["notes"].strip() for e in hist),
    )
    check(
        "нет префикса «День N» в exam",
        all(not re.match(r"^День\s+\d+", e["exam"]) for e in hist),
        next((e["exam"][:40] for e in hist if re.match(r"^День\s+\d+", e["exam"])), ""),
    )
    check(
        "нет префикса «Состояние» в notes",
        all(not e["notes"].startswith("Состояние") for e in hist),
    )
    exams = [e["exam"] for e in hist]
    notes = [e["notes"] for e in hist]
    check("уникальные exam", len(exams) == len(set(exams)), f"dup={len(exams)-len(set(exams))}")
    check("уникальные notes", len(notes) == len(set(notes)), f"dup={len(notes)-len(set(notes))}")

    traj = simulate_trajectory("baseline", {**p, "ward_stay_days": 14})
    check("simulate days 1..14", [t["day"] for t in traj] == list(range(1, 15)))

    cohort = load_cohort()
    check("когорта не пуста", len(cohort) >= 3, str(len(cohort)))
    for cp in cohort:
        stay = int(cp.get("ward_stay_days") or 14)
        wh = cp.get("ward_history") or []
        got = [int(e.get("day") or 0) for e in wh]
        check(
            f"{cp['synthetic_id']} ward 1..{stay}",
            got == list(range(1, stay + 1)),
            str(got[:5]),
        )
        neg = [
            n
            for n in (cp.get("health_notes") or [])
            if str(n.get("date") or "").startswith("day-")
        ]
        check(f"{cp['synthetic_id']} нет day-N в шапке", not neg, str(neg[:1]))


def test_notes_sync() -> None:
    section("Notes sync / dedupe")
    from digital_resident.patients import (
        build_ward_history,
        sync_state_notes,
        dedupe_sort_health_notes,
        format_note_day_label,
    )

    notes = dedupe_sort_health_notes(
        [
            {"date": "day7", "text": "старое"},
            {"date": "day07", "text": "новое"},
            {"date": "day-7", "text": "преданамнез не должен мешать"},
        ]
    )
    by = {n["date"]: n["text"] for n in notes}
    check("канон day07→day7 overwrite", by.get("day7") == "новое", str(by))

    p = {
        "synthetic_id": "TEST-SYNC",
        "full_name": "Sync",
        "diagnosis": "АГ",
        "scenario": "baseline",
        "bp_office": "150/95",
        "hr": 70,
        "weight_kg": 80,
        "labs_day0": {"k_mmol_l": 4.0, "egfr": 88, "creatinine_umol_l": 90, "glucose_mmol_l": 5.0},
        "ward_stay_days": 6,
        "health_notes": [
            {"date": "day-7", "text": "Не должно попасть в шапку"},
            {"date": "day1", "text": "Клиническая day1 из карточки."},
        ],
    }
    p["ward_history"] = build_ward_history(p, stay_days=6)
    p = sync_state_notes(p)
    dates = [n["date"] for n in p["health_notes"]]
    check("шапка без day-7", "day-7" not in dates, str(dates))
    check("шапка содержит day1..day6", dates == [f"day{i}" for i in range(1, 7)], str(dates))
    check("label поступления", format_note_day_label("day1", stay_days=6) == "1 · поступление")
    check("label выписки", format_note_day_label("day6", stay_days=6) == "6 · выписка")


def test_safety() -> None:
    section("Safety / auditor rules")
    from digital_resident.safety import run_safety_checks, enforce_plan_constraints, classify_med_list

    comorbid = {
        "allergies": ["Эналаприл — ангионевротический отёк"],
        "consent_invasive": False,
        "labs_day0": {"egfr": 38, "k_mmol_l": 4.9},
        "notes": "ангиоотёк на иАПФ",
    }
    bad_plan = {
        "medications": [
            {"name": "Эналаприл 10 мг", "dose": "10 мг"},
            {"name": "Гидрохлоротиазид 12.5 мг", "dose": "12.5"},
        ]
    }
    findings = run_safety_checks(comorbid, bad_plan)
    ids = {f.get("rule_id") for f in findings}
    check("ACEI_ANGIOEDEMA", "ACEI_ANGIOEDEMA" in ids, str(ids))
    check("PROC_CONSENT", "PROC_CONSENT" in ids, str(ids))
    check("THIAZIDE_GFR45 или LOW", ("THIAZIDE_LOW_GFR" in ids) or ("THIAZIDE_GFR45" in ids), str(ids))

    dual = {
        "medications": [
            {"name": "Периндоприл 5 мг"},
            {"name": "Валсартан 80 мг"},
        ]
    }
    f2 = run_safety_checks({"labs_day0": {"egfr": 90, "k_mmol_l": 4.2}, "consent_invasive": True}, dual)
    check("DD_DUAL_RAAS", any(f.get("rule_id") == "DD_DUAL_RAAS" for f in f2))

    fixed = enforce_plan_constraints(comorbid, bad_plan)
    clas = classify_med_list(
        [f"{m.get('name','')} {m.get('dose','')}" for m in (fixed.get("medications") or [])]
    )
    check("enforce убирает ACEI при ангиоотёке", not clas["acei"], str(clas))


def test_simulation_scenarios() -> None:
    section("Simulation scenarios")
    from digital_resident.simulation import simulate_trajectory, needs_replan
    from digital_resident.cases import get_case

    base = get_case("baseline")["patient"]
    base["ward_stay_days"] = 14
    tb = simulate_trajectory("baseline", base)
    check("baseline без replan", not needs_replan(tb))

    com = get_case("comorbid")["patient"]
    com["ward_stay_days"] = 14
    tc = simulate_trajectory("comorbid_ckd", com)
    check("comorbid traj len 14", len(tc) == 14)
    check("comorbid day1 flags", "prefer_arb_over_acei" in (tc[0].get("flags") or []))

    cmp_ = get_case("complication")["patient"]
    cmp_["ward_stay_days"] = 14
    th = simulate_trajectory("hyperkalemia_day3", cmp_)
    check("complication needs_replan", needs_replan(th))
    d3 = next(t for t in th if t["day"] == 3)
    check("day3 hyperkalemia flag", "hyperkalemia" in (d3.get("flags") or []), str(d3.get("flags")))
    check("day3 K+>=5.5", float(d3["labs"]["k_mmol_l"]) >= 5.5, str(d3["labs"]))


def test_citations() -> None:
    section("Citations validation")
    from digital_resident.citations import validate_and_repair_plan

    hits = [
        {"section": "§3.1", "page": 10, "chunk_id": "c1", "text": "иРААС"},
        {"section": "§3.2", "page": 12, "chunk_id": "c2", "text": "АК"},
    ]
    plan = {
        "medications": [
            {"name": "Валсартан", "citations": ["[1]", "[99]"]},
        ],
        "examinations": [{"item": "ЭКГ", "citations": ["[2]"]}],
        "citations_used": [{"ref": "[1]", "section": "wrong", "page": "1"}],
    }
    fixed, issues = validate_and_repair_plan(plan, hits)
    med_cites = (fixed.get("medications") or [{}])[0].get("citations") or []
    check("[99] убран из meds", "[99]" not in med_cites, str(med_cites))
    check("[1] сохранён", "[1]" in med_cites, str(med_cites))


def test_rag_integration() -> None:
    section("RAG integration")
    from digital_resident.rag import GuidelineRAG
    from digital_resident.cases import get_case

    rag = GuidelineRAG()
    check("chroma collection > 0", rag.count > 0, f"count={rag.count}")
    if rag.count == 0:
        return
    patient = get_case("comorbid")["patient"]
    hits = rag.search_for_patient(patient, k=8)
    check("search_for_patient возвращает hits", len(hits) >= 3, str(len(hits)))
    must = {h.get("chunk_id") for h in hits}
    check("есть curated/must chunks", any(str(c).startswith("cur_") for c in must), str(list(must)[:5]))
    ctx = rag.format_context(hits)
    check("format_context с [1]", "[1]" in ctx)


def test_cases_catalog() -> None:
    section("Assignment cases catalog")
    from digital_resident.cases import list_cases, get_case

    ids = {c["id"] for c in list_cases()}
    check("3 кейса ТЗ", ids == {"baseline", "comorbid", "complication"}, str(ids))
    for cid in ("baseline", "comorbid", "complication"):
        c = get_case(cid)
        check(f"{cid} patient", bool(c.get("patient")))
        check(f"{cid} scenario", bool(c.get("scenario")))


def test_imports_architecture() -> None:
    section("Architecture imports")
    from digital_resident.agents import run_case, run_patient
    from digital_resident.agents.graph import build_graph

    g = build_graph()
    check("LangGraph build_graph", g is not None)
    check("run_case callable", callable(run_case))
    check("run_patient callable", callable(run_patient))


def main() -> int:
    print("REGRESSION / INTEGRATION (offline)")
    tests = [
        test_ward_days,
        test_notes_sync,
        test_safety,
        test_simulation_scenarios,
        test_citations,
        test_rag_integration,
        test_cases_catalog,
        test_imports_architecture,
    ]
    for fn in tests:
        try:
            fn()
        except Exception:
            global FAIL
            FAIL += 1
            ERRORS.append(f"EXCEPTION in {fn.__name__}: {traceback.format_exc()}")
            print(traceback.format_exc())

    print(f"\n=== SUMMARY offline: PASS={PASS} FAIL={FAIL} ===")
    for e in ERRORS:
        print(" ", e.split("\n")[0])
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
