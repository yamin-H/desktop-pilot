import asyncpg
import pytest


def vector(size: int) -> str:
    return "[" + ",".join(["0.1"] * size) + "]"


async def add_document(pool, source="a.md") -> int:
    return await pool.fetchval(
        "INSERT INTO documents (source, title, content_hash) VALUES ($1, 'A', 'h') RETURNING id",
        source,
    )


async def add_chunk(pool, document_id: int, size: int = 384, index: int = 0) -> None:
    await pool.execute(
        "INSERT INTO document_chunks (document_id, chunk_index, heading, content, embedding) "
        "VALUES ($1, $2, 'Limits', 'Withdrawal rules apply', $3::text::vector)",
        document_id,
        index,
        vector(size),
    )


async def test_pgvector_is_installed(pool):
    name = await pool.fetchval("SELECT extname FROM pg_extension WHERE extname = 'vector'")
    assert name == "vector"


async def test_a_chunk_builds_its_keyword_search_text_from_heading_and_content(pool):
    await add_chunk(pool, await add_document(pool))
    query = "SELECT count(*) FROM document_chunks WHERE tsv @@ to_tsquery('english', $1)"
    assert await pool.fetchval(query, "withdrawal") == 1  # from the content (stemmed)
    assert await pool.fetchval(query, "limits") == 1  # from the heading
    assert await pool.fetchval(query, "banana") == 0


async def test_a_vector_of_the_wrong_size_is_refused(pool):
    document_id = await add_document(pool)
    with pytest.raises(asyncpg.PostgresError):
        await add_chunk(pool, document_id, size=3)


async def test_deleting_a_document_deletes_its_chunks(pool):
    document_id = await add_document(pool)
    await add_chunk(pool, document_id)
    await pool.execute("DELETE FROM documents WHERE id = $1", document_id)
    assert await pool.fetchval("SELECT count(*) FROM document_chunks") == 0


async def test_a_source_name_can_only_exist_once(pool):
    await add_document(pool, "same.md")
    with pytest.raises(asyncpg.UniqueViolationError):
        await add_document(pool, "same.md")


async def test_chunk_numbers_are_unique_within_a_document(pool):
    document_id = await add_document(pool)
    await add_chunk(pool, document_id, index=0)
    with pytest.raises(asyncpg.UniqueViolationError):
        await add_chunk(pool, document_id, index=0)
