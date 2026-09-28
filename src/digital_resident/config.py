from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env", override=True)


def settings() -> dict:
    return {
        "root": ROOT,
        "neural_deep_api_key": os.getenv("NEURAL_DEEP_API_KEY", "").strip(),
        "neural_deep_base_url": os.getenv(
            "NEURAL_DEEP_BASE_URL", "https://api.neuraldeep.tech/v1"
        ).strip(),
        "neural_deep_model": os.getenv("NEURAL_DEEP_MODEL", "qwen3.8-27b-noreason").strip(),
        "llm7_api_key": os.getenv("LLM7_API_KEY", "").strip(),
        "llm7_base_url": os.getenv("LLM7_BASE_URL", "https://api.llm7.io/v1").strip(),
        "llm7_model": os.getenv("LLM7_MODEL", "codestral-latest").strip(),
        "embedding_model": os.getenv("EMBEDDING_MODEL", "bge-m3").strip(),
        "guideline_txt": ROOT / "data" / "guidelines" / "kr_ag_2024.txt",
        "chunks_json": ROOT / "data" / "guidelines" / "chunks.json",
        "chroma_dir": ROOT / "data" / "chroma",
        "collection_name": "kr_ag_2024",
    }


def has_llm_api_key() -> bool:
    """Есть ли ключ для живого LLM / embeddings (не коммитьте ключи в git)."""
    s = settings()
    return bool(s["neural_deep_api_key"] or s["llm7_api_key"])
