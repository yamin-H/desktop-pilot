import pytest

from deskpilot.rag.chunker import Chunk
from deskpilot.rag.embedder import HashingEmbedder
from deskpilot.rag.search import hybrid_search
from deskpilot.rag.store import DocumentStore, EmbeddedChunk, or_query

EMBEDDER = HashingEmbedder()


def embedded(texts, heading=None, page=None):
    vectors = EMBEDDER.embed(texts)
    return [
        EmbeddedChunk(Chunk(index, text, heading, page), vector)
        for index, (text, vector) in enumerate(zip(texts, vectors, strict=True))
    ]


async def put(store, source, texts, *, title=None, heading=None, page=None, content_hash="h1"):
    await store.replace_document(
        source, title or source, content_hash, embedded(texts, heading, page)
    )


async def vector_hits(store, text, limit=5):
    [vector] = EMBEDDER.embed([text])
    return await store.vector_search(vector, limit)


async def test_a_stored_document_is_listed_with_its_chunks_and_fingerprint(pool):
    store = DocumentStore(pool)
    assert await store.get_hash("a.md") is None
    await put(store, "a.md", ["one", "two", "three"], title="Alpha", content_hash="abc")

    assert await store.get_hash("a.md") == "abc"
    [info] = await store.list_documents()
    assert (info.source, info.title, info.content_hash, info.chunks) == ("a.md", "Alpha", "abc", 3)


async def test_storing_a_document_again_replaces_it_completely(pool):
    store = DocumentStore(pool)
    await put(store, "a.md", ["old text one", "old text two"], content_hash="v1")
    await put(store, "a.md", ["new text"], content_hash="v2")

    [info] = await store.list_documents()
    assert (info.chunks, info.content_hash) == (1, "v2")
    assert await store.text_search(or_query("old"), 5) == []


async def test_deleting_reports_whether_anything_was_deleted(pool):
    store = DocumentStore(pool)
    await put(store, "a.md", ["text"])
    assert await store.delete_document("a.md") is True
    assert await store.delete_document("a.md") is False
    assert await store.list_documents() == []


async def test_vector_search_returns_the_closest_chunk_first(pool):
    store = DocumentStore(pool)
    await put(store, "a.md", ["withdrawal limits per day", "banana smoothie recipe"])
    hits = await vector_hits(store, "withdrawal limits per day")
    assert hits[0].content == "withdrawal limits per day"
    assert hits[0].score == pytest.approx(1.0, abs=1e-4)  # identical text
    assert hits[0].score > hits[1].score


async def test_vector_search_always_returns_the_nearest_even_if_unrelated(pool):
    store = DocumentStore(pool)
    await put(store, "a.md", ["alpha", "beta"])
    assert len(await vector_hits(store, "completely different words", limit=5)) == 2


async def test_text_search_finds_words_and_stems(pool):
    store = DocumentStore(pool)
    await put(store, "a.md", ["Withdrawal limits apply daily", "Feeds reconnect by themselves"])
    hits = await store.text_search(or_query("what is the withdrawal limit?"), 5)
    assert [hit.content for hit in hits] == ["Withdrawal limits apply daily"]


async def test_text_search_also_looks_at_headings(pool):
    store = DocumentStore(pool)
    await put(store, "a.md", ["plain body"], heading="Settlement windows")
    assert len(await store.text_search(or_query("settlement"), 5)) == 1


async def test_text_search_with_nothing_searchable_returns_nothing(pool):
    store = DocumentStore(pool)
    await put(store, "a.md", ["some text"])
    assert await store.text_search("", 5) == []
    assert await store.text_search(or_query("the and of"), 5) == []  # only filler words


async def test_a_hit_carries_everything_needed_for_a_citation(pool):
    store = DocumentStore(pool)
    await put(store, "docs/a.md", ["text about limits"], title="Alpha", heading="Limits", page=7)
    [hit] = await store.text_search(or_query("limits"), 5)
    assert (hit.source, hit.title, hit.heading, hit.page) == ("docs/a.md", "Alpha", "Limits", 7)


async def test_hybrid_search_ranks_a_chunk_found_both_ways_first(pool):
    store = DocumentStore(pool)
    await put(
        store,
        "a.md",
        [
            "missing_in_ledger break means the statement lists a trade we never recorded",
            "feeds reconnect by themselves with growing pauses",
            "average cost is not changed by selling",
        ],
    )
    hits = await hybrid_search(store, EMBEDDER, "what is a missing_in_ledger break")
    assert hits[0].content.startswith("missing_in_ledger break")
    assert hits[0].found_by == ("vector", "text")


async def test_a_question_with_no_matching_words_still_gets_meaning_hits_only(pool):
    store = DocumentStore(pool)
    await put(store, "a.md", ["alpha text", "beta text"])
    hits = await hybrid_search(store, EMBEDDER, "zzzz qqqq")
    assert hits
    assert all(hit.found_by == ("vector",) for hit in hits)


async def test_hybrid_search_respects_the_limit(pool):
    store = DocumentStore(pool)
    await put(store, "a.md", [f"chunk number {i}" for i in range(10)])
    assert len(await hybrid_search(store, EMBEDDER, "chunk number", limit=3)) == 3
