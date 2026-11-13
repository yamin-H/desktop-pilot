import pytest

from deskpilot.rag.embedder import EmbeddingError, HashingEmbedder
from deskpilot.rag.search import Hit, fuse, hybrid_search
from deskpilot.rag.store import RawHit, or_query, vector_literal


def raw(chunk_id: int) -> RawHit:
    return RawHit(chunk_id, "a.md", "Title", None, None, chunk_id, f"text {chunk_id}", 0.0)


def test_a_chunk_found_by_both_searches_beats_chunks_found_by_one():
    hits = fuse({"vector": [raw(1), raw(2), raw(3)], "text": [raw(3), raw(4)]})
    # chunk 3: 1/63 + 1/61. Chunks 2 and 4 tie on 1/62, so the lower id comes first.
    assert [hit.chunk_id for hit in hits] == [3, 1, 2, 4]
    assert hits[0].score == pytest.approx(1 / 63 + 1 / 61)
    assert hits[0].found_by == ("vector", "text")
    assert hits[1].found_by == ("vector",)
    assert hits[3].found_by == ("text",)


def test_fusing_nothing_gives_nothing():
    assert fuse({"vector": [], "text": []}) == []
    assert fuse({}) == []


def test_a_hit_knows_how_to_be_cited():
    def hit(heading, page):
        return Hit(1, "a.md", "Runbook", heading, page, 0, "x", 0.0, ("text",))

    assert hit(None, None).citation == "Runbook"
    assert hit("Runbook > Missing", None).citation == 'Runbook, section "Runbook > Missing"'
    assert hit(None, 4).citation == "Runbook, page 4"
    assert hit("Limits", 4).citation == 'Runbook, section "Limits", page 4'


def test_a_keyword_query_joins_words_with_or_and_removes_repeats():
    assert or_query("How do I fix a missing_in_ledger break?") == (
        "how | do | i | fix | a | missing | in | ledger | break"
    )
    assert or_query("fee FEE Fee") == "fee"


def test_a_keyword_query_cannot_contain_search_operators():
    assert or_query("a&b | c:* ; DROP") == "a | b | c | drop"


def test_a_keyword_query_is_capped():
    assert len(or_query(" ".join(f"w{i}" for i in range(100))).split(" | ")) == 20


def test_text_without_words_gives_an_empty_query():
    assert or_query("?!. ") == ""


def test_a_vector_is_written_as_text():
    assert vector_literal([0.1, -2.0, 1e-9]) == "[0.1,-2,1e-09]"


class FakeStore:
    def __init__(self, by_meaning, by_words):
        self._by_meaning, self._by_words = by_meaning, by_words
        self.text_queries = []

    async def vector_search(self, embedding, limit):
        assert len(embedding) == 384
        return self._by_meaning[:limit]

    async def text_search(self, query, limit):
        self.text_queries.append(query)
        return self._by_words[:limit]


async def test_hybrid_search_merges_both_searches_and_applies_the_limit():
    store = FakeStore([raw(1), raw(2), raw(3)], [raw(3), raw(9)])
    hits = await hybrid_search(store, HashingEmbedder(), "missing trade", limit=2)
    assert [hit.chunk_id for hit in hits] == [3, 1]
    assert store.text_queries == ["missing | trade"]


async def test_an_empty_question_searches_nothing():
    store = FakeStore([raw(1)], [raw(2)])
    assert await hybrid_search(store, HashingEmbedder(), "   ") == []
    assert store.text_queries == []


async def test_an_embedder_with_the_wrong_size_is_refused_before_searching():
    class Wrong(HashingEmbedder):
        dimension = 768

    store = FakeStore([raw(1)], [])
    with pytest.raises(EmbeddingError, match="768"):
        await hybrid_search(store, Wrong(), "question")
    assert store.text_queries == []
