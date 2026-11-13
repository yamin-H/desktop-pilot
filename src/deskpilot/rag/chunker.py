import re
from collections.abc import Sequence
from dataclasses import dataclass

# From the biggest natural break to the smallest. We cut at the biggest one that works.
_SEPARATORS = ("\n\n", "\n", ". ", " ")


@dataclass(frozen=True)
class Section:
    """A piece of a document that has a heading and/or a page number."""

    text: str
    heading: str | None = None
    page: int | None = None


@dataclass(frozen=True)
class Chunk:
    index: int  # position in the whole document
    text: str
    heading: str | None
    page: int | None


def _pieces(text: str, limit: int, separators: tuple[str, ...]) -> list[str]:
    """Cut text into pieces of at most `limit` characters. Every character is kept."""
    if len(text) <= limit:
        return [text]
    if not separators:
        return [text[i : i + limit] for i in range(0, len(text), limit)]
    separator, rest = separators[0], separators[1:]
    parts = text.split(separator)
    pieces: list[str] = []
    for index, part in enumerate(parts):
        piece = part + (separator if index < len(parts) - 1 else "")
        pieces.extend(_pieces(piece, limit, rest) if len(piece) > limit else [piece])
    return pieces


def _pack(pieces: list[str], limit: int) -> list[str]:
    """Glue neighbouring pieces together while they still fit."""
    packed: list[str] = []
    current = ""
    for piece in pieces:
        if current and len(current) + len(piece) > limit:
            packed.append(current)
            current = ""
        current += piece
    if current:
        packed.append(current)
    return packed


def _tail(previous: str, overlap: int) -> str:
    """The last `overlap` characters of the previous chunk, starting at a whole word."""
    if overlap == 0 or not previous:
        return ""
    tail = previous[-overlap:]
    cut_inside_a_word = (
        len(previous) > overlap and not previous[-overlap - 1].isspace() and not tail[0].isspace()
    )
    if cut_inside_a_word:
        match = re.search(r"\s", tail)
        tail = tail[match.end() :] if match else ""
    return tail.strip()


def chunk_sections(
    sections: Sequence[Section], *, max_chars: int = 1000, overlap: int = 150
) -> list[Chunk]:
    """Cut sections into chunks of at most `max_chars` characters.

    Cuts happen at paragraph, line, sentence or word boundaries, in that order of
    preference. With `overlap`, each chunk starts with the end of the previous chunk of the
    same section, so an answer that straddles a cut can still be found.
    """
    if max_chars < 100:
        raise ValueError("max_chars must be at least 100")
    if not 0 <= overlap <= max_chars // 2:
        raise ValueError("overlap must be between 0 and half of max_chars")

    # room for the new text, once the overlap and the joining space are counted
    limit = max_chars - overlap - (1 if overlap else 0)

    chunks: list[Chunk] = []
    for section in sections:
        previous = ""
        for raw in _pack(_pieces(section.text, limit, _SEPARATORS), limit):
            core = raw.strip()
            if not core:
                continue
            tail = _tail(previous, overlap)
            text = f"{tail} {core}" if tail else core
            chunks.append(Chunk(len(chunks), text, section.heading, section.page))
            previous = core
    return chunks
