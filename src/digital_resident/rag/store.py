from __future__ import annotations

import re
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings

from digital_resident.config import settings
from digital_resident.llm import get_llm
from digital_resident.rag.chunker import load_or_build_chunks, save_chunks


class GuidelineRAG:
    def __init__(self) -> None:
        s = settings()
        self.persist_dir = str(s["chroma_dir"])
        self.collection_name = s["collection_name"]
        self.client = chromadb.PersistentClient(
            path=self.persist_dir,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        self._cache: list[dict[str, Any]] | None = None

    @property
    def count(self) -> int:
        return self.collection.count()

    def _all_chunks(self) -> list[dict[str, Any]]:
        if self._cache is not None:
            return self._cache
        if self.count == 0:
            return []
        raw = self.collection.get(include=["documents", "metadatas"])
        out = []
        for i, cid in enumerate(raw["ids"]):
            meta = (raw["metadatas"] or [{}])[i] or {}
            out.append(
                {
                    "chunk_id": cid,
                    "id": cid,
                    "text": (raw["documents"] or [""])[i] or "",
                    "section": meta.get("section", ""),
                    "page": meta.get("page", ""),
                    "source": meta.get("source", ""),
                    "citation": f"{meta.get('section', 'КР')} (стр. {meta.get('page', '?')})",
                }
            )
        self._cache = out
        return out

    def build(self, force: bool = False) -> int:
        if self.count > 0 and not force:
            return self.count
        if force and self.count > 0:
            self.client.delete_collection(self.collection_name)
            self.collection = self.client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "cosine"},
            )
            self._cache = None
        chunks = load_or_build_chunks(include_full_text=True)
        save_chunks(chunks)
        llm = get_llm()
        ids = [c["id"] for c in chunks]
        docs = [c["text"] for c in chunks]
        metas = [
            {
                "section": c["section"],
                "page": int(c.get("page", 0) or 0),
                "source": c.get("source", ""),
                "chunk_id": c["id"],
            }
            for c in chunks
        ]
        embeddings = llm.embed(docs)
        batch = 32
        for i in range(0, len(ids), batch):
            self.collection.add(
                ids=ids[i : i + batch],
                documents=docs[i : i + batch],
                metadatas=metas[i : i + batch],
                embeddings=embeddings[i : i + batch],
            )
        self._cache = None
        return self.count

    def _vector_search(self, query: str, k: int) -> list[dict[str, Any]]:
        emb = get_llm().embed([query])[0]
        res = self.collection.query(
            query_embeddings=[emb],
            n_results=min(max(k, 1), max(self.count, 1)),
            include=["documents", "metadatas", "distances"],
        )
        out: list[dict[str, Any]] = []
        if not res["documents"] or not res["documents"][0]:
            return out
        ids = (res.get("ids") or [[]])[0]
        for i, doc in enumerate(res["documents"][0]):
            meta = res["metadatas"][0][i] or {}
            dist = res["distances"][0][i] if res.get("distances") else None
            cid = ids[i] if i < len(ids) else meta.get("chunk_id", "")
            out.append(
                {
                    "chunk_id": cid,
                    "id": cid,
                    "text": doc,
                    "section": meta.get("section", ""),
                    "page": meta.get("page", ""),
                    "source": meta.get("source", ""),
                    "distance": dist,
                    "score": 1.0 - float(dist) if dist is not None else 0.0,
                    "citation": f"{meta.get('section', 'КР')} (стр. {meta.get('page', '?')})",
                    "via": "vector",
                }
            )
        return out

    def _keyword_search(self, query: str, k: int = 8) -> list[dict[str, Any]]:
        tokens = [t for t in re.split(r"[^\wа-яА-ЯёЁ]+", query.lower()) if len(t) >= 4]
        prefer = [
            "гиперкалием",
            "спиронолактон",
            "тиазид",
            "хбп",
            "скф",
            "иапф",
            "ангио",
            "стартов",
            "комбинац",
            "петлев",
            "противопоказ",
            "ираас",
        ]
        tokens = list(dict.fromkeys(tokens + prefer))
        scored: list[tuple[float, dict[str, Any]]] = []
        for ch in self._all_chunks():
            blob = f"{ch.get('section','')} {ch.get('text','')}".lower()
            hit = sum(1 for t in tokens if t in blob)
            # boost curated
            if str(ch.get("chunk_id", "")).startswith("cur_"):
                hit += 1.5
            if hit <= 0:
                continue
            item = dict(ch)
            item["score"] = float(hit)
            item["via"] = "keyword"
            item["distance"] = None
            scored.append((item["score"], item))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [x for _, x in scored[:k]]

    def search(
        self,
        query: str,
        k: int = 6,
        *,
        must_include_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        if self.count == 0:
            self.build()
        vector = self._vector_search(query, k=max(k, 8))
        keyword = self._keyword_search(query, k=max(k, 8))

        merged: dict[str, dict[str, Any]] = {}
        for rank, h in enumerate(vector):
            cid = h["chunk_id"]
            merged[cid] = dict(h)
            merged[cid]["score"] = merged[cid].get("score", 0) + (1.0 / (1 + rank))
        for rank, h in enumerate(keyword):
            cid = h["chunk_id"]
            if cid not in merged:
                merged[cid] = dict(h)
                merged[cid]["score"] = 0.0
            merged[cid]["score"] = merged[cid].get("score", 0) + 0.8 / (1 + rank)
            merged[cid]["via"] = "hybrid"

        # force clinically critical curated chunks when requested
        by_id = {c["chunk_id"]: c for c in self._all_chunks()}
        for mid in must_include_ids or []:
            if mid in by_id and mid not in merged:
                item = dict(by_id[mid])
                item["score"] = 2.5
                item["via"] = "must"
                merged[mid] = item
            elif mid in merged:
                merged[mid]["score"] = merged[mid].get("score", 0) + 2.0
                merged[mid]["via"] = "must+hybrid"

        ranked = sorted(merged.values(), key=lambda x: x.get("score", 0), reverse=True)
        return ranked[:k]

    def search_for_patient(self, patient: dict[str, Any], k: int = 8) -> list[dict[str, Any]]:
        labs = patient.get("labs_day0") or {}
        dx = str(patient.get("diagnosis") or "").strip()
        queries = [
            # диагноз — главный запрос: при смене диагноза подтягиваются другие фрагменты
            f"клинические рекомендации лечение {dx}",
            (
                f"стартовая комбинированная терапия АГ иРААС АК диуретик {dx}"
            ),
            (
                f"коморбидности {', '.join(patient.get('comorbidities') or [])} "
                f"аллергии {', '.join(patient.get('allergies') or [])} "
                f"рСКФ {labs.get('egfr')} калий {labs.get('k_mmol_l')}"
            ),
            "противопоказания иАПФ БРА гиперкалиемия ангионевротический отек мониторинг калия СКФ",
        ]
        must = ["cur_start_combo", "cur_five_classes", "cur_monitoring_labs"]
        allergies = " ".join(patient.get("allergies") or []).lower()
        dx_l = dx.lower()
        if "ангио" in allergies or "эналаприл" in allergies or "иапф" in allergies:
            must += ["cur_angioedema", "cur_iraas_contra"]
            queries.append("ангионевротический отек иАПФ предпочтение БРА")
        egfr = float(labs.get("egfr") or 999)
        if (
            egfr < 60
            or any("хбп" in c.lower() for c in (patient.get("comorbidities") or []))
            or "хбп" in dx_l
        ):
            must += ["cur_ckd_start", "cur_ckd_targets", "cur_thiazide_ckd"]
            queries.append("АГ и ХБП стартовая терапия тиазид петлевой диуретик СКФ")
        if float(labs.get("k_mmol_l") or 0) >= 5.0 or "гиперкали" in dx_l:
            must += ["cur_iraas_contra", "cur_spironolactone"]
            queries.append("гиперкалиемия противопоказание иАПФ БРА спиронолактон")
        if "резистент" in dx_l:
            must += ["cur_spironolactone", "cur_triple"]
            queries.append("резистентная артериальная гипертензия спиронолактон тройная терапия")

        bag: dict[str, dict[str, Any]] = {}
        for q in queries:
            for h in self.search(q, k=6, must_include_ids=must):
                cid = h["chunk_id"]
                if cid not in bag or h.get("score", 0) > bag[cid].get("score", 0):
                    bag[cid] = h
        # ensure must present
        by_id = {c["chunk_id"]: c for c in self._all_chunks()}
        for mid in must:
            if mid in by_id:
                item = dict(by_id[mid])
                item["score"] = max(item.get("score", 0), 3.0)
                item["via"] = "must"
                bag[mid] = item
        ranked = sorted(bag.values(), key=lambda x: x.get("score", 0), reverse=True)
        return ranked[:k]

    def format_context(self, hits: list[dict[str, Any]]) -> str:
        blocks = []
        for i, h in enumerate(hits, 1):
            blocks.append(
                f"[{i}] section=\"{h.get('section','')}\" page={h.get('page','')} "
                f"chunk_id={h.get('chunk_id','')}\n"
                f"Источник: {h.get('source', '')}\n{h.get('text', '')}"
            )
        return "\n\n".join(blocks)
