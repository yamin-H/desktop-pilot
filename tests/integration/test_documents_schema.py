import asyncpg
import pytest


def vector(*head: float) -> str:
    """A 384-dimension vector in pgvector's text form, starting with `head`, zeros after."""
    values = [*head, *([0.0] * (384 - len(head)))]
    return "[" + ",".join(str(v) for v in values) + "]"


async def add_document(pool, source="docs/binance.md") -> int:
    return await pool.fetchval(
        "INSERT INTO documents (source, title, doc_type, content_hash) "
        "VALUES ($1, 'Title', 'exchange_docs', 'hash') RETURNING id",
        source,
    )


async def add_chunk(pool, document_id, index, content, embedding, heading=None):
    await pool.execute(
        "INSERT INTO chunks (document_id, chunk_index, heading, content, token_count, "
        "embedding, embedding_model) VALUES ($1, $2, $3, $4, 10, $5::text::vector, 'test-model')",
        document_id,
        index,
        heading,
        content,
        embedding,
    )


async def test_the_vector_extension_and_indexes_exist(pool):
    assert await pool.fetchval("SELECT 1 FROM pg_extension WHERE extname = 'vector'") == 1
    names = {
        r["indexname"]
        for r in await pool.fetch("SELECT indexname FROM pg_indexes WHERE tablename = 'chunks'")
    }
    assert {"chunks_embedding_hnsw_idx", "chunks_tsv_idx"} <= names


async def test_vector_search_finds_the_nearest_chunk(pool):
    doc = await add_document(pool)
    await add_chunk(pool, doc, 0, "weights and rate limits", vector(1, 0))
    await add_chunk(pool, doc, 1, "nonce rules for private calls", vector(0, 1))
    nearest = await pool.fetchval(
        "SELECT chunk_index FROM chunks ORDER BY embedding <=> $1::text::vector LIMIT 1",
        vector(0.9, 0.1),
    )
    assert nearest == 0


async def test_keyword_search_finds_exact_terms_and_the_heading(pool):
    doc = await add_document(pool)
    await add_chunk(pool, doc, 0, "Requests are weighted.", vector(1), heading="Rate limits")
    await add_chunk(pool, doc, 1, "Every private call needs a nonce.", vector(0, 1))
    query = "SELECT chunk_index FROM chunks WHERE tsv @@ plainto_tsquery('english', $1)"
    assert [r["chunk_index"] for r in await pool.fetch(query, "nonce")] == [1]
    assert [r["chunk_index"] for r in await pool.fetch(query, "rate limits")] == [0]


async def test_deleting_a_document_deletes_its_chunks(pool):
    doc = await add_document(pool)
    await add_chunk(pool, doc, 0, "text", vector(1))
    await pool.execute("DELETE FROM documents WHERE id = $1", doc)
    assert await pool.fetchval("SELECT count(*) FROM chunks") == 0


async def test_a_vector_of_the_wrong_size_is_refused(pool):
    doc = await add_document(pool)
    with pytest.raises(asyncpg.PostgresError):
        await add_chunk(pool, doc, 0, "text", "[1,2,3]")


async def test_a_chunk_index_cannot_repeat_inside_a_document(pool):
    doc = await add_document(pool)
    await add_chunk(pool, doc, 0, "first", vector(1))
    with pytest.raises(asyncpg.UniqueViolationError):
        await add_chunk(pool, doc, 0, "second", vector(0, 1))
