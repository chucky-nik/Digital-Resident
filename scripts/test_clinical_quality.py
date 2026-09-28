#!/usr/bin/env python3
"""Клинические golden-тесты: дозы, hard-stop hyperK, формуляр, классы по 3 кейсам."""
from __future__ import annotations

import sys
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


def test_formulary_parse() -> None:
    section("Formulary / dose parse")
    from digital_resident.dosing import (
        is_vague_dose,
        parse_mg_values,
        repair_medication_dose,
        validate_medication_dose,
        enforce_iraas_stop_on_hyperkalemia,
        match_drug,
    )

    check("parse 5 мг", parse_mg_values("5 мг 1 р/сут") == [5.0])
    check("parse combo", parse_mg_values("5 мг + 5 мг") == [5.0, 5.0])
    check("vague начальная", is_vague_dose("Начальная доза"))
    check("vague hedge", is_vague_dose("Отмена или снижение дозы"))
    check("ok numeric", not is_vague_dose("5 мг 1 р/сут"))
    check("match perindopril", match_drug("Периндоприл (иАПФ)") == "периндоприл")

    bad = {"name": "Амлодипин", "dose": "100 мг 1 р/сут"}
    issues = validate_medication_dose(bad)
    check("100 мг амлодипин out of range", any(i["rule_id"] == "DOSE_OUT_OF_RANGE" for i in issues))
    fixed = repair_medication_dose(bad)
    check("repair clamps amlodipine", "5" in str(fixed.get("dose")))

    vague = {"name": "Периндоприл", "dose": "Начальная доза"}
    fixed2 = repair_medication_dose(vague)
    check("repair vague perindopril", "5" in str(fixed2.get("dose")) and "мг" in str(fixed2.get("dose")))

    lethal = {"name": "Периндоприл", "dose": "500 мг"}
    issues2 = validate_medication_dose(lethal)
    check("500 мг perindopril rejected", any(i["rule_id"] == "DOSE_OUT_OF_RANGE" for i in issues2))


def test_hyperk_force_stop() -> None:
    section("HyperK force stop")
    from digital_resident.dosing import enforce_iraas_stop_on_hyperkalemia, is_stop_action, active_med_names
    from digital_resident.safety import classify_med_list, run_safety_checks

    plan = {
        "medications": [
            {"name": "Периндоприл", "dose": "Отмена или снижение дозы", "action": "reduce"},
            {"name": "Амлодипин", "dose": "Начальная доза"},
        ]
    }
    traj = [{"day": 3, "labs": {"k_mmol_l": 5.7, "egfr": 34}, "flags": ["hyperkalemia", "recalculate_plan"]}]
    out = enforce_iraas_stop_on_hyperkalemia(plan, traj)
    peri = next(m for m in out["medications"] if "ериндоприл" in m["name"].lower() or "периндоприл" in m["name"].lower())
    check("perindopril stopped", is_stop_action(peri), str(peri))
    check("no hedge left", "или" not in str(peri.get("dose")).lower(), str(peri.get("dose")))
    active = active_med_names(out)
    clas = classify_med_list(active)
    check("no active ACEI after stop", not clas["acei"], str(active))

    # amlodipine should get repaired if we also run dose repair — force stop alone keeps vague;
    # enforce_plan_constraints does both
    from digital_resident.safety import enforce_plan_constraints
    from digital_resident.cases import get_case

    patient = get_case("complication")["patient"]
    out2 = enforce_plan_constraints(patient, out)
    out2 = enforce_iraas_stop_on_hyperkalemia(out2, traj)
    amlo = next(m for m in out2["medications"] if "амлодипин" in m["name"].lower())
    check("amlodipine numeric after enforce", "мг" in str(amlo.get("dose")) and not is_stop_action(amlo), str(amlo))

    findings = run_safety_checks(patient, plan, out2, traj)
    ids = {f["rule_id"] for f in findings}
    check("no IRAAS_ACTIVE finding when stopped", "TRAJ_HYPERK_IRAAS_ACTIVE" not in ids, str(ids))


def test_case_class_expectations() -> None:
    section("Golden class expectations (offline enforce)")
    from digital_resident.cases import get_case
    from digital_resident.safety import (
        allergy_blocks_acei,
        classify_med_list,
        enforce_plan_constraints,
        med_names,
        run_safety_checks,
    )
    from digital_resident.dosing import parse_mg_values

    # comorbid: ACEI must be swapped to ARB with numeric dose
    com = get_case("comorbid")
    assert allergy_blocks_acei(com["patient"])
    raw = {
        "medications": [
            {"name": "Эналаприл", "dose": "10 мг", "citations": ["[1]"]},
            {"name": "Амлодипин", "dose": "5 мг", "citations": ["[1]"]},
        ],
        "monitoring": [],
    }
    fixed = enforce_plan_constraints(com["patient"], raw)
    clas = classify_med_list(med_names(fixed, None))
    check("comorbid no ACEI after enforce", not clas["acei"])
    check("comorbid has ARB", clas["arb"])
    check("comorbid has CCB", clas["ccb"])
    for m in fixed["medications"]:
        if not isinstance(m, dict):
            continue
        check(f"comorbid dose mg: {m.get('name')}", bool(parse_mg_values(str(m.get("dose")))), str(m.get("dose")))

    findings = run_safety_checks(com["patient"], fixed, None, [])
    ids = {f["rule_id"] for f in findings}
    check("comorbid still flags missing consent", "PROC_CONSENT" in ids, str(ids))
    check("comorbid ACEI finding cleared", "ACEI_ANGIOEDEMA" not in ids, str(ids))

    # baseline-like combo
    base = get_case("baseline")
    raw_b = {
        "medications": [
            {
                "name": "Периндоприл + Амлодипин",
                "dose": "5 мг + 5 мг 1 р/сут",
                "citations": ["[1]"],
            }
        ],
        "monitoring": [{"item": "контроль калия и рСКФ"}],
    }
    fb = enforce_plan_constraints(base["patient"], raw_b)
    for m in fb["medications"]:
        check("baseline dose numeric", bool(parse_mg_values(str(m.get("dose")))), str(m))
    issues = run_safety_checks(base["patient"], fb, None, [])
    dose_bad = [f for f in issues if str(f.get("rule_id", "")).startswith("DOSE_")]
    check("baseline no dose findings", not dose_bad, str(dose_bad))


def test_rag_dose_chunk() -> None:
    section("RAG dose chunk available")
    from digital_resident.rag import GuidelineRAG
    from digital_resident.cases import get_case

    rag = GuidelineRAG()
    hits = rag.search_for_patient(get_case("baseline")["patient"], k=10)
    ids = {h.get("chunk_id") for h in hits}
    check("cur_dose_table in patient hits", "cur_dose_table" in ids, str(ids))
    blob = " ".join(h.get("text", "") for h in hits).lower()
    check("hits mention мг doses", "мг" in blob and "периндоприл" in blob)


def test_simulation_med_sensitive() -> None:
    section("Simulation depends on plan_meds")
    from digital_resident.cases import get_case
    from digital_resident.simulation import needs_replan, simulate_trajectory

    p = get_case("complication")["patient"]
    with_iraas = simulate_trajectory(
        "hyperkalemia_day3", p, plan_meds=["Периндоприл 5 мг", "Амлодипин 5 мг"]
    )
    without = simulate_trajectory(
        "hyperkalemia_day3", p, plan_meds=["Амлодипин 5 мг"]
    )
    check("with IRAAS needs replan", needs_replan(with_iraas))
    check("without IRAAS no severe replan", not needs_replan(without))
    d3_on = next(x for x in with_iraas if int(x["day"]) == 3)
    d3_off = next(x for x in without if int(x["day"]) == 3)
    check("with IRAAS day3 K>=5.5", float(d3_on["labs"]["k_mmol_l"]) >= 5.5)
    check("without IRAAS day3 K<5.5", float(d3_off["labs"]["k_mmol_l"]) < 5.5)

    com = get_case("comorbid")["patient"]
    t_acei = simulate_trajectory("comorbid_ckd", com, plan_meds=["Периндоприл 5 мг"])
    t_none = simulate_trajectory("comorbid_ckd", com, plan_meds=["Амлодипин 5 мг"])
    check(
        "ACEI raises K faster on CKD",
        t_acei[-1]["labs"]["k_mmol_l"] > t_none[-1]["labs"]["k_mmol_l"],
        f"{t_acei[-1]['labs']['k_mmol_l']} vs {t_none[-1]['labs']['k_mmol_l']}",
    )


def test_enforce_hard_rules() -> None:
    section("Enforce hard clinical stops")
    from digital_resident.cases import get_case
    from digital_resident.dosing import is_stop_action, active_med_names
    from digital_resident.safety import (
        classify_med_list,
        enforce_plan_constraints,
        med_names,
    )

    # K>=5.5 → stop IRAAS
    p = dict(get_case("baseline")["patient"])
    p["labs_day0"] = dict(p["labs_day0"])
    p["labs_day0"]["k_mmol_l"] = 5.6
    out = enforce_plan_constraints(
        p, {"medications": [{"name": "Периндоприл", "dose": "5 мг"}], "monitoring": []}
    )
    peri = out["medications"][0]
    check("baseline hyperK stops ACEI", is_stop_action(peri), peri)

    # dual RAAS → stop ACEI keep ARB
    p2 = get_case("baseline")["patient"]
    out2 = enforce_plan_constraints(
        p2,
        {
            "medications": [
                {"name": "Эналаприл", "dose": "10 мг"},
                {"name": "Лозартан", "dose": "50 мг"},
            ],
            "monitoring": [{"item": "калий"}],
        },
    )
    clas = classify_med_list(med_names(out2, None))
    check("dual RAAS no active ACEI", not clas["acei"], clas)
    check("dual RAAS keeps ARB", clas["arb"], clas)

    # thiazide at egfr 25 → loop
    p3 = dict(get_case("comorbid")["patient"])
    p3["labs_day0"] = dict(p3["labs_day0"])
    p3["labs_day0"]["egfr"] = 25
    p3["labs_day0"]["k_mmol_l"] = 4.5
    out3 = enforce_plan_constraints(
        p3,
        {"medications": [{"name": "Индапамид", "dose": "1.5 мг"}], "monitoring": []},
    )
    names = " ".join(active_med_names(out3)).lower()
    check("thiazide→furosemide", "фуросемид" in names, names)


def test_simulation_complication() -> None:
    section("Simulation complication")
    from digital_resident.cases import get_case
    from digital_resident.simulation import needs_replan, simulate_trajectory

    p = get_case("complication")["patient"]
    traj = simulate_trajectory("hyperkalemia_day3", p)
    check("needs replan", needs_replan(traj))
    d3 = next(x for x in traj if int(x["day"]) == 3)
    check("day3 K>=5.5", float(d3["labs"]["k_mmol_l"]) >= 5.5)


def main() -> int:
    print("CLINICAL QUALITY TESTS")
    test_formulary_parse()
    test_hyperk_force_stop()
    test_case_class_expectations()
    test_rag_dose_chunk()
    test_simulation_complication()
    test_simulation_med_sensitive()
    test_enforce_hard_rules()
    print(f"\n=== SUMMARY clinical: PASS={PASS} FAIL={FAIL} ===")
    for e in ERRORS:
        print(" ", e)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
