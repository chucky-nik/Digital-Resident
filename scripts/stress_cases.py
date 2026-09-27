#!/usr/bin/env python3
"""Прогон 3 кейсов × 3 раза с отчётом об ошибках."""
from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from digital_resident.agents import run_case
from digital_resident.rag import GuidelineRAG
from digital_resident.safety import classify_med_list, med_names


def check_result(case_id: str, result: dict) -> list[str]:
    errs: list[str] = []
    plan = result.get("plan") or {}
    if plan.get("parse_error"):
        errs.append("plan parse_error")
    if not plan.get("medications"):
        errs.append("no medications")
    cv = plan.get("citation_validation") or {}
    if cv.get("invalid_removed", 0) > 0:
        errs.append(f"invalid citations removed={cv.get('invalid_removed')}")
    if result.get("citation_issues"):
        errs.append(f"citation_issues={len(result['citation_issues'])}")
    traj = result.get("trajectory") or []
    stay = int((result.get("patient") or {}).get("ward_stay_days") or 14)
    expected_days = list(range(0, stay + 1))
    got_days = [t.get("day") for t in traj]
    if got_days != expected_days:
        errs.append(f"bad trajectory days {got_days[:5]}… (expected daily 0..{stay})")
    audit = result.get("audit") or {}
    if "findings" not in audit:
        errs.append("no audit findings key")

    clas = classify_med_list(med_names(plan, result.get("revised_plan")))
    if case_id == "comorbid" and clas["acei"]:
        errs.append("comorbid still has ACEI")
    if case_id == "comorbid" and not clas["arb"]:
        errs.append("comorbid missing ARB")
    if case_id == "complication" and not result.get("revised_plan"):
        errs.append("complication missing revised_plan")
    if case_id == "baseline" and result.get("revised_plan"):
        errs.append("baseline unexpectedly revised")
    if case_id == "comorbid":
        findings = " ".join(f.get("title", "") for f in (audit.get("findings") or []))
        if "соглас" not in findings.lower():
            errs.append("comorbid auditor missed consent")
    return errs


def main() -> int:
    rag = GuidelineRAG()
    if rag.count == 0:
        print("Building RAG...")
        print(rag.build())

    report = []
    fail = 0
    for case_id in ["baseline", "comorbid", "complication"]:
        for i in range(1, 4):
            print(f"=== {case_id} run {i}/3 ===", flush=True)
            try:
                result = run_case(case_id)
                out = ROOT / "data" / f"result_{case_id}.json"
                out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                errs = check_result(case_id, result)
                status = "OK" if not errs else "WARN"
                if errs:
                    fail += 1
                line = {
                    "case": case_id,
                    "run": i,
                    "status": status,
                    "errors": errs,
                    "meds": [
                        m.get("name") if isinstance(m, dict) else str(m)
                        for m in (result.get("plan") or {}).get("medications") or []
                    ],
                    "revised": bool(result.get("revised_plan")),
                    "findings": len((result.get("audit") or {}).get("findings") or []),
                    "caught": ((result.get("audit") or {}).get("caught_example") or "")[:160],
                }
                report.append(line)
                print(json.dumps(line, ensure_ascii=False), flush=True)
            except Exception as e:
                fail += 1
                tb = traceback.format_exc()
                report.append({"case": case_id, "run": i, "status": "FAIL", "errors": [str(e)], "traceback": tb})
                print("FAIL", e, flush=True)
                print(tb, flush=True)

    out_rep = ROOT / "data" / "stress_report.json"
    out_rep.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved {out_rep}; failures/warns={fail}/{len(report)}")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
