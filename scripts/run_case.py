#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from digital_resident.agents import run_case
from digital_resident.rag import GuidelineRAG


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--case", default="comorbid", choices=["baseline", "comorbid", "complication"])
    p.add_argument("--build-rag", action="store_true")
    args = p.parse_args()
    rag = GuidelineRAG()
    if args.build_rag or rag.count == 0:
        print("Building RAG...")
        print("chunks:", rag.build(force=args.build_rag))
    result = run_case(args.case)
    out = ROOT / "data" / f"result_{args.case}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("saved", out)
    audit = result.get("audit") or {}
    print("audit findings:", len(audit.get("findings") or []))
    print("caught:", audit.get("caught_example", "")[:300])


if __name__ == "__main__":
    main()
