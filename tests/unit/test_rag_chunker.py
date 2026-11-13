import re

import pytest

from deskpilot.rag.chunker import Section, chunk_sections


def words(count: int) -> str:
    return " ".join(f"w{i:03d}" for i in range(count))


def squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


def test_a_short_section_is_one_chunk_with_its_heading_and_page():
    [chunk] = chunk_sections([Section("Hello world.", "Intro", 3)])
    assert (chunk.index, chunk.text, chunk.heading, chunk.page) == (0, "Hello world.", "Intro", 3)


def test_empty_sections_give_no_chunks():
    assert chunk_sections([Section("  \n\n "), Section("")]) == []


def test_paragraphs_are_packed_together_while_they_fit():
    text = "A" * 300 + "\n\n" + "B" * 300
    [chunk] = chunk_sections([Section(text)], max_chars=1000, overlap=0)
    assert chunk.text == text


def test_a_long_section_is_cut_at_paragraph_boundaries_first():
    text = "\n\n".join(letter * 400 for letter in "ABC")
    chunks = chunk_sections([Section(text)], max_chars=1000, overlap=0)
    assert [c.text for c in chunks] == ["A" * 400 + "\n\n" + "B" * 400, "C" * 400]


def test_a_paragraph_without_breaks_is_cut_between_sentences():
    text = " ".join(f"Sentence number {i:02d} is here." for i in range(40))
    chunks = chunk_sections([Section(text)], max_chars=300, overlap=0)
    assert len(chunks) > 1
    assert all(c.text.endswith("here.") for c in chunks)
    assert all(len(c.text) <= 300 for c in chunks)


def test_a_word_longer_than_the_limit_is_cut_by_characters():
    chunks = chunk_sections([Section("x" * 2500)], max_chars=1000, overlap=0)
    assert [len(c.text) for c in chunks] == [1000, 1000, 500]


@pytest.mark.parametrize("max_chars", [100, 250, 1000])
def test_nothing_is_lost_without_overlap(max_chars):
    text = "\n\n".join(f"Paragraph {i}. " + words(40) for i in range(8))
    chunks = chunk_sections([Section(text)], max_chars=max_chars, overlap=0)
    assert squash("".join(c.text for c in chunks)) == squash(text)


@pytest.mark.parametrize("overlap", [0, 20, 50])
def test_no_chunk_is_longer_than_the_limit(overlap):
    text = "\n\n".join(words(60) for _ in range(5)) + " " + "x" * 500
    chunks = chunk_sections([Section(text)], max_chars=100, overlap=overlap)
    assert all(len(c.text) <= 100 for c in chunks)


def test_overlap_repeats_the_end_of_the_previous_chunk_without_cutting_words():
    text = words(200)
    chunks = chunk_sections([Section(text)], max_chars=100, overlap=30)
    assert len(chunks) > 2
    all_words = set(text.split())
    for previous, current in zip(chunks, chunks[1:], strict=False):
        tokens = current.text.split()
        assert set(tokens) <= all_words  # no word was cut in half
        assert tokens[0] in previous.text.split()  # it starts with words from the chunk before


def test_chunks_are_numbered_across_sections_and_keep_their_own_heading_and_page():
    chunks = chunk_sections([Section("one", "A", 1), Section("two", "B", 2)])
    assert [(c.index, c.heading, c.page) for c in chunks] == [(0, "A", 1), (1, "B", 2)]


def test_overlap_never_crosses_from_one_section_into_the_next():
    chunks = chunk_sections([Section("first part", "A"), Section("second part", "B")])
    assert chunks[1].text == "second part"


@pytest.mark.parametrize(("max_chars", "overlap"), [(99, 0), (100, -1), (100, 51), (1000, 501)])
def test_bad_settings_are_refused(max_chars, overlap):
    with pytest.raises(ValueError):
        chunk_sections([Section("text")], max_chars=max_chars, overlap=overlap)
