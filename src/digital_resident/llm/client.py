from __future__ import annotations

from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from digital_resident.config import settings


class LLMClient:
    """Neural Deep как основной провайдер, llm7 — fallback."""

    def __init__(self) -> None:
        s = settings()
        if not s["neural_deep_api_key"]:
            raise RuntimeError("NEURAL_DEEP_API_KEY не задан в .env")
        self.primary = OpenAI(
            base_url=s["neural_deep_base_url"],
            api_key=s["neural_deep_api_key"],
            timeout=90.0,
        )
        self.primary_model = s["neural_deep_model"]
        self.fallback = None
        self.fallback_model = s["llm7_model"]
        if s["llm7_api_key"]:
            self.fallback = OpenAI(
                base_url=s["llm7_base_url"],
                api_key=s["llm7_api_key"],
                timeout=90.0,
            )
        self.embedding_model = s["embedding_model"]

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=8))
    def chat(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2000,
    ) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        try:
            r = self.primary.chat.completions.create(
                model=self.primary_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return (r.choices[0].message.content or "").strip()
        except Exception:
            if not self.fallback:
                raise
            r = self.fallback.chat.completions.create(
                model=self.fallback_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return (r.choices[0].message.content or "").strip()

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Эмбеддинги через Neural Deep (bge-m3) — без локальных тяжёлых моделей."""
        if not texts:
            return []
        out: list[list[float]] = []
        batch = 16
        for i in range(0, len(texts), batch):
            chunk = texts[i : i + batch]
            r = self.primary.embeddings.create(
                model=self.embedding_model,
                input=chunk,
            )
            data = sorted(r.data, key=lambda x: getattr(x, "index", 0))
            out.extend([d.embedding for d in data])
        return out


_llm: LLMClient | None = None


def get_llm() -> LLMClient:
    global _llm
    if _llm is None:
        _llm = LLMClient()
    return _llm
