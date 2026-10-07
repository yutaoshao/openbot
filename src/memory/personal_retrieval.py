"""Hybrid paragraph retrieval; answers always read the current Markdown version."""

from __future__ import annotations

import asyncio
import hashlib
import math
from collections import Counter
from typing import Any

from src.core.logging import get_logger
from src.memory.personal_profile import PersonalProfile, ProfileMatch, _terms

logger = get_logger(__name__)
_EMBEDDING_BATCH_SIZE = 32


class PersonalRetrieval:
    def __init__(
        self, profile: PersonalProfile, *, index: Any, embedding: Any, reranker: Any = None
    ) -> None:
        self.profile = profile
        self.index = index
        self.embedding = embedding
        self.reranker = reranker
        self._lock = asyncio.Lock()

    def _embedding_model(self) -> str:
        config = getattr(self.embedding, "config", None)
        return ":".join(
            str(getattr(config, field, "disabled"))
            for field in ("provider", "model", "dimensions", "enabled")
        )

    async def rebuild(self) -> list[dict]:
        """Refresh changed/deleted docs; existing vectors are merely a revision cache."""
        async with self._lock:
            cached = {item["id"]: item for item in await self.index.all()}
            model = self._embedding_model()
            chunks = await asyncio.to_thread(self._document_chunks, cached, model)
            missing = [item for item in chunks if not item["embedding"]]
            for offset in range(0, len(missing), _EMBEDDING_BATCH_SIZE):
                batch = missing[offset : offset + _EMBEDDING_BATCH_SIZE]
                vectors = await self.embedding.embed_batch([item["content"] for item in batch])
                if len(vectors) != len(batch):
                    raise ValueError("Profile embedding batch size does not match the input")
                for item, vector in zip(batch, vectors, strict=True):
                    item["embedding"] = vector
            if chunks != list(cached.values()):
                await self.index.replace(chunks)
            logger.info(
                "personal_index.refreshed",
                chunks=len(chunks),
                vectors=sum(bool(item["embedding"]) for item in chunks),
            )
            return chunks

    def _document_chunks(self, cached: dict[str, dict], model: str) -> list[dict]:
        chunks = []
        for path in self.profile.documents():
            content, revision = self.profile.read_document(path)
            for section, text in paragraphs(content):
                chunk_id = hashlib.sha256(f"{path}\n{section}\n{text}".encode()).hexdigest()
                item = cached.get(chunk_id, {})
                vector = item.get("embedding", []) if item.get("embedding_model") == model else []
                chunks.append(
                    dict(
                        id=chunk_id,
                        path=path,
                        revision=revision,
                        section=section,
                        content=text,
                        embedding_model=model,
                        embedding=vector,
                    )
                )
        return chunks

    async def recall(self, query: str, *, limit: int = 3) -> list[ProfileMatch]:
        chunks = await self.rebuild()
        query_vector = await self.embedding.embed(query)
        # Paragraphs repeat the dossier title for display; exclude that title
        # from lexical scoring so a broad subject query does not rank every
        # paragraph equally.
        keyword_scores = bm25(query, [_chunk_search_text(item) for item in chunks])
        lexical = sorted(range(len(chunks)), key=lambda i: keyword_scores[i], reverse=True)
        vector_scores = [cosine(query_vector, item["embedding"]) for item in chunks]
        semantic = sorted(range(len(chunks)), key=lambda i: vector_scores[i], reverse=True)
        scores: dict[int, float] = {}
        for ranking, values in ((lexical, keyword_scores), (semantic, vector_scores)):
            for rank, index in enumerate([i for i in ranking if values[i] > 0][:20]):
                scores[index] = scores.get(index, 0) + 1 / (60 + rank + 1)
        direct = await asyncio.to_thread(self.profile.matches, query, limit=max(limit, 12))
        by_path: dict[str, dict] = {}
        direct_paths = {match.path.relative_to(self.profile.root).as_posix() for match in direct}
        for match in direct:
            path = match.path.relative_to(self.profile.root).as_posix()
            by_path[path] = dict(
                path=path,
                content=match.content,
                revision=hashlib.sha256(match.content.encode()).hexdigest(),
                score=float(match.score),
            )
        for index, score in sorted(scores.items(), key=lambda pair: -pair[1]):
            item = chunks[index]
            path = item["path"]
            if path not in by_path:
                by_path[path] = {**item, "score": score, "_chunk_score": score}
            elif path in direct_paths and score > by_path[path].get("_chunk_score", 0):
                by_path[path]["content"] = item["content"]
                by_path[path]["_chunk_score"] = score
            elif path not in direct_paths:
                by_path[path]["score"] = max(by_path[path]["score"], score)
        candidates = sorted(by_path.values(), key=lambda item: -item["score"])[:20]
        if self.reranker and candidates:
            candidates = await self.reranker.rerank_dicts(
                query, candidates, content_key="content", top_n=min(12, len(candidates))
            )
        result: list[ProfileMatch] = []
        for item in candidates:
            if len(result) >= limit:
                break
            try:
                content, revision = await asyncio.to_thread(
                    self.profile.read_document, item["path"]
                )
            except FileNotFoundError:
                logger.info("personal_index.stale_hit", path=item["path"], reason="deleted")
                continue
            if revision != item["revision"]:
                logger.info("personal_index.stale_hit", path=item["path"], reason="edited")
                continue
            selected_sections = _retrieved_sections(chunks, scores, item["path"])
            result.append(
                ProfileMatch(
                    path=self.profile.root / item["path"],
                    title=content.splitlines()[0].lstrip("# "),
                    content=content,
                    source=str(self.profile.root / item["path"]),
                    score=item["score"],
                    sections=selected_sections,
                )
            )
        logger.info(
            "personal_profile.lookup",
            query=query,
            candidates=[
                {"path": item["path"], "revision": item["revision"]} for item in candidates
            ],
            sources=[
                {"path": item.source, "revision": hashlib.sha256(item.content.encode()).hexdigest()}
                for item in result
            ],
            used_vectors=bool(query_vector),
        )
        return result


def _retrieved_sections(
    chunks: list[dict], scores: dict[int, float], path: str, *, limit: int = 8
) -> tuple[str, ...]:
    ranked = sorted(
        (
            (score, index, item["content"])
            for index, item in enumerate(chunks)
            if item["path"] == path and (score := scores.get(index, 0)) > 0
        ),
        key=lambda value: (-value[0], value[1]),
    )
    if ranked:
        return tuple(item[2] for item in ranked[:limit])
    # A title-only match has no paragraph score. Keep a small deterministic
    # preview instead of expanding the whole dossier into the prompt.
    return tuple(item["content"] for item in chunks if item["path"] == path)[:limit]


def _chunk_search_text(item: dict) -> str:
    lines = item["content"].splitlines()
    return "\n".join(lines[2:]) if len(lines) > 2 else item["content"]


def paragraphs(content: str) -> list[tuple[str, str]]:
    title = content.split("\n", 1)[0]
    section = ""
    output = []
    current = []
    for line in content.splitlines()[1:]:
        if line.startswith("## ") or line.startswith("- "):
            if current:
                output.append((section, f"{title}\n{section}\n" + "\n".join(current)))
            current = []
        if line.startswith("## "):
            section = line[3:]
        elif line.strip():
            current.append(line)
    if current:
        output.append((section, f"{title}\n{section}\n" + "\n".join(current)))
    return output


def bm25(query: str, documents: list[str]) -> list[float]:
    terms = _terms(query)
    tokens = [_terms(text) for text in documents]
    size = max(len(tokens), 1)
    frequencies = Counter(term for item in tokens for term in item)
    average = sum(map(len, tokens)) / size or 1
    return [
        sum(
            math.log(1 + (size - frequencies[term] + 0.5) / (frequencies[term] + 0.5))
            * 2.2
            / (1 + 1.2 * (0.25 + 0.75 * len(item) / average))
            for term in terms & item
        )
        for item in tokens
    ]


def cosine(first: list[float], second: list[float]) -> float:
    if not first or len(first) != len(second):
        return 0
    denominator = math.sqrt(sum(x * x for x in first) * sum(x * x for x in second))
    return (
        sum(a * b for a, b in zip(first, second, strict=True)) / denominator if denominator else 0
    )
