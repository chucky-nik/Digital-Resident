#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from digital_resident.rag import GuidelineRAG


def main() -> None:
    p = argparse.ArgumentParser(description="Build Chroma RAG index for KR AG 2024")
    p.add_argument("--force", action="store_true")
    args = p.parse_args()
    rag = GuidelineRAG()
    n = rag.build(force=args.force)
    print(f"OK: {n} chunks in {rag.persist_dir}")


if __name__ == "__main__":
    main()
