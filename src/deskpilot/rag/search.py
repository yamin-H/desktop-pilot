import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from deskpilot.rag.embedder import EMBEDDING_DIMENSION, Embedder, EmbeddingError
from deskpilot.rag.store import DocumentStore, RawHit, or_query


@dataclass(frozen=True)
class Hit:
    """A passage found by search, with what is needed to cite it."""

    chunk_id: int
    source: str
    title: str
    heading: str | None
    page: int | None
    chunk_index: int
    content: str
    score: float  # fusion score: only meaningful for ordering, not as a percentage
    found_by: tuple[str, ...]  # 'vector' (by meaning) and/or 'text' (by words)

    @property
    def citation(self) -> str:
        parts = [self.title]
        if self.heading:
            parts.append(f'section "{self.heading}"')
        if self.page is not None:
            parts.append(f"page {self.page}")
        return ", ".join(parts)


def fuse(rankings: Mapping[str, Sequence[RawHit]], *, k: int = 60) -> list[Hit]:
    """Merge ranked lists with reciprocal rank fusion.

    A chunk scores 1 / (k + rank) in every list that contains it, and the scores add up.
    A chunk ranked well by two searches beats one ranked first by only one.
    """
    scores: dict[int, float] = {}
    chunks: dict[int, RawHit] = {}
    found_by: dict[int, list[str]] = {}
    for method, hits in rankings.items():
        for rank, hit in enumerate(hits, start=1):
            scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1.0 / (k + rank)
            chunks.setdefault(hit.chunk_id, hit)
            found_by.setdefault(hit.chunk_id, []).append(method)

    ordered = sorted(scores, key=lambda chunk_id: (-scores[chunk_id], chunk_id))
    return [
        Hit(
            chunk_id=chunk_id,
            source=chunks[chunk_id].source,
            title=chunks[chunk_id].title,
            heading=chunks[chunk_id].heading,
            page=chunks[chunk_id].page,
            chunk_index=chunks[chunk_id].chunk_index,
            content=chunks[chunk_id].content,
            score=scores[chunk_id],
            found_by=tuple(found_by[chunk_id]),
        )
        for chunk_id in ordered
    ]


async def hybrid_search(
    store: DocumentStore,
    embedder: Embedder,
    query: str,
    *,
    limit: int = 5,
    candidates: int = 20,
) -> list[Hit]:
    """Search by meaning and by words, then merge. Returns at most `limit` passages."""
    query = query.strip()
    if not query:
        return []
    if embedder.dimension != EMBEDDING_DIMENSION:
        raise EmbeddingError(
            f"embedder {embedder.name} has {embedder.dimension} dimensions, "
            f"the database expects {EMBEDDING_DIMENSION}"
        )
    [vector] = await asyncio.to_thread(embedder.embed, [query])  # keep the event loop free
    by_meaning, by_words = await asyncio.gather(
        store.vector_search(vector, candidates),
        store.text_search(or_query(query), candidates),
    )
    return fuse({"vector": by_meaning, "text": by_words})[:limit]
