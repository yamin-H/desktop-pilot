import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

import asyncpg

from deskpilot.rag.chunker import Chunk

_TERM = re.compile(r"[a-z0-9]+")

_INSERT_DOCUMENT = """
INSERT INTO documents (source, title, content_hash) VALUES ($1, $2, $3) RETURNING id
"""

_INSERT_CHUNK = """
INSERT INTO document_chunks (document_id, chunk_index, heading, page, content, embedding)
VALUES ($1, $2, $3, $4, $5, $6::text::vector)
"""

_VECTOR_SEARCH = """
SELECT c.id AS chunk_id, d.source, d.title, c.heading, c.page, c.chunk_index, c.content,
       1 - (c.embedding <=> $1::text::vector) AS score
FROM document_chunks c
JOIN documents d ON d.id = c.document_id
ORDER BY c.embedding <=> $1::text::vector
LIMIT $2
"""

_TEXT_SEARCH = """
SELECT c.id AS chunk_id, d.source, d.title, c.heading, c.page, c.chunk_index, c.content,
       ts_rank_cd(c.tsv, q.query) AS score
FROM document_chunks c
JOIN documents d ON d.id = c.document_id
CROSS JOIN (SELECT to_tsquery('english', $1) AS query) q
WHERE c.tsv @@ q.query
ORDER BY score DESC, c.id
LIMIT $2
"""

_LIST_DOCUMENTS = """
SELECT d.source, d.title, d.content_hash, d.ingested_at, count(c.id) AS chunks
FROM documents d
LEFT JOIN document_chunks c ON c.document_id = d.id
GROUP BY d.id
ORDER BY d.source
"""


@dataclass(frozen=True)
class EmbeddedChunk:
    chunk: Chunk
    embedding: list[float]


@dataclass(frozen=True)
class RawHit:
    """One chunk found by one search method."""

    chunk_id: int
    source: str
    title: str
    heading: str | None
    page: int | None
    chunk_index: int
    content: str
    score: float  # similarity (vector search) or keyword rank (text search)


@dataclass(frozen=True)
class DocumentInfo:
    source: str
    title: str
    content_hash: str
    ingested_at: datetime
    chunks: int


def vector_literal(values: Sequence[float]) -> str:
    """A vector as text, which PostgreSQL turns into a vector: '[0.1,0.2,...]'."""
    return "[" + ",".join(format(value, ".8g") for value in values) + "]"


def or_query(text: str, max_terms: int = 20) -> str:
    """Words from free text as a keyword query: 'a | b | c'.

    Only letters and digits survive, so the text can never inject search operators.
    PostgreSQL drops filler words like 'the' by itself.
    """
    terms = list(dict.fromkeys(_TERM.findall(text.lower())))[:max_terms]
    return " | ".join(terms)


class DocumentStore:
    """Saves and searches document chunks. The only code that touches these tables."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def get_hash(self, source: str) -> str | None:
        return await self._pool.fetchval(
            "SELECT content_hash FROM documents WHERE source = $1", source
        )

    async def replace_document(
        self, source: str, title: str, content_hash: str, chunks: Sequence[EmbeddedChunk]
    ) -> None:
        """Store a document, replacing any earlier version completely, in one transaction."""
        rows = [
            (
                item.chunk.index,
                item.chunk.heading,
                item.chunk.page,
                item.chunk.text,
                vector_literal(item.embedding),
            )
            for item in chunks
        ]
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute("DELETE FROM documents WHERE source = $1", source)
            document_id = await conn.fetchval(_INSERT_DOCUMENT, source, title, content_hash)
            await conn.executemany(_INSERT_CHUNK, [(document_id, *row) for row in rows])

    async def delete_document(self, source: str) -> bool:
        status = await self._pool.execute("DELETE FROM documents WHERE source = $1", source)
        return int(status.rsplit(" ", 1)[-1]) > 0  # "DELETE 1" -> True

    async def list_documents(self) -> list[DocumentInfo]:
        rows = await self._pool.fetch(_LIST_DOCUMENTS)
        return [DocumentInfo(**dict(row)) for row in rows]

    async def vector_search(self, embedding: Sequence[float], limit: int) -> list[RawHit]:
        """The chunks closest in meaning. Always returns the nearest ones, even if unrelated."""
        rows = await self._pool.fetch(_VECTOR_SEARCH, vector_literal(embedding), limit)
        return [RawHit(**dict(row)) for row in rows]

    async def text_search(self, query: str, limit: int) -> list[RawHit]:
        """The chunks containing the words of `query` (built with or_query)."""
        if not query.strip():
            return []
        rows = await self._pool.fetch(_TEXT_SEARCH, query, limit)
        return [RawHit(**dict(row)) for row in rows]
