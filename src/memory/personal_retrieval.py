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
            chunks = []
            for path in self.profile.documents():
                content, revision = self.profile.read_document(path)
                for section, text in paragraphs(content):
                    chunk_id = hashlib.sha256(f"{path}\n{section}\n{text}".encode()).hexdigest()
                    item = cached.get(chunk_id, {})
                    vector = (
                        item.get("embedding", []) if item.get("embedding_model") == model else []
                    )
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
            missing = [item for item in chunks if not item["embedding"]]
            if missing:
                vectors = await self.embedding.embed_batch([item["content"] for item in missing])
                if len(vectors) != len(missing):
                    raise ValueError("Profile embedding batch size does not match the input")
                for item, vector in zip(missing, vectors, strict=True):
                    item["embedding"] = vector
            if chunks != list(cached.values()):
                await self.index.replace(chunks)
            logger.info(
                "personal_index.refreshed",
                chunks=len(chunks),
                vectors=sum(bool(item["embedding"]) for item in chunks),
            )
            return chunks

    async def recall(self, query: str, *, limit: int = 3) -> list[ProfileMatch]:
        chunks = await self.rebuild()
        query_vector = await self.embedding.embed(query)
        keyword_scores = bm25(query, [item["content"] for item in chunks])
        lexical = sorted(range(len(chunks)), key=lambda i: keyword_scores[i], reverse=True)
        vector_scores = [cosine(query_vector, item["embedding"]) for item in chunks]
        semantic = sorted(range(len(chunks)), key=lambda i: vector_scores[i], reverse=True)
        scores: dict[int, float] = {}
        for ranking, values in ((lexical, keyword_scores), (semantic, vector_scores)):
            for rank, index in enumerate([i for i in ranking if values[i] > 0][:20]):
                scores[index] = scores.get(index, 0) + 1 / (60 + rank + 1)
        candidates = [
            {**chunks[i], "score": score}
            for i, score in sorted(scores.items(), key=lambda pair: -pair[1])
        ]
        if self.reranker and candidates:
            candidates = await self.reranker.rerank_dicts(
                query, candidates, content_key="content", top_n=min(12, len(candidates))
            )
        direct = self.profile.matches(query, limit=limit)
        result = list(direct)
        for item in candidates:
            if len(result) >= limit:
                break
            if any(match.path == self.profile.root / item["path"] for match in result):
                continue
            try:
                content, revision = self.profile.read_document(item["path"])
            except FileNotFoundError:
                logger.info("personal_index.stale_hit", path=item["path"], reason="deleted")
                continue
            if revision != item["revision"]:
                logger.info("personal_index.stale_hit", path=item["path"], reason="edited")
                continue
            result.append(
                ProfileMatch(
                    path=self.profile.root / item["path"],
                    title=content.splitlines()[0].lstrip("# "),
                    content=content,
                    source=str(self.profile.root / item["path"]),
                    score=item["score"],
                )
            )
        logger.info(
            "personal_profile.lookup",
            query=query,
            sources=[
                {"path": item.source, "revision": hashlib.sha256(item.content.encode()).hexdigest()}
                for item in result
            ],
            used_vectors=bool(query_vector),
        )
        return result


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
