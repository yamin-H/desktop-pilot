from types import SimpleNamespace

import pytest

from deskpilot.rag.embedder import EmbeddingError, FastEmbedEmbedder, HashingEmbedder


def similarity(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def test_vectors_have_the_right_size_and_unit_length():
    [vector] = HashingEmbedder().embed(["reconciliation break missing trade"])
    assert len(vector) == 384
    assert similarity(vector, vector) == pytest.approx(1.0)


def test_the_same_text_always_gives_the_same_vector():
    embedder = HashingEmbedder()
    assert embedder.embed(["a b c"]) == embedder.embed(["a b c"])


def test_texts_sharing_words_are_closer_than_unrelated_texts():
    a, b, c = HashingEmbedder().embed(
        [
            "reconciliation break missing trade",
            "reconciliation break missing record",
            "weather sunny holiday beach",
        ]
    )
    assert similarity(a, b) > similarity(a, c) + 0.3


@pytest.mark.parametrize("text", ["", "   ", "???"])
def test_a_text_without_words_still_gets_a_usable_vector(text):
    [vector] = HashingEmbedder().embed([text])
    assert similarity(vector, vector) == pytest.approx(1.0)


def test_the_real_embedder_does_not_load_its_model_until_it_is_used():
    embedder = FastEmbedEmbedder()
    assert (embedder.name, embedder.dimension) == ("BAAI/bge-small-en-v1.5", 384)
    assert embedder._model is None


def test_the_real_embedder_returns_plain_floats():
    embedder = FastEmbedEmbedder()
    embedder._model = SimpleNamespace(embed=lambda texts: [[0.5] * 384 for _ in texts])
    vectors = embedder.embed(["a", "b"])
    assert len(vectors) == 2
    assert all(isinstance(value, float) for value in vectors[0])


def test_a_model_with_the_wrong_size_is_refused_with_both_numbers():
    embedder = FastEmbedEmbedder()
    embedder._model = SimpleNamespace(embed=lambda texts: [[0.5] * 768 for _ in texts])
    with pytest.raises(EmbeddingError, match="768.*384"):
        embedder.embed(["a"])
