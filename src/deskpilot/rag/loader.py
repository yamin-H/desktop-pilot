import io
import re
from dataclasses import dataclass
from pathlib import PurePath

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from deskpilot.rag.chunker import Section

SUPPORTED = (".md", ".markdown", ".txt", ".pdf")

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")


class DocumentLoadError(ValueError):
    """The file cannot be turned into text we can search."""


@dataclass(frozen=True)
class ParsedDocument:
    title: str
    sections: tuple[Section, ...]


def _parse_markdown(text: str, fallback_title: str) -> ParsedDocument:
    """Split by headings. A section's heading is its path, like 'Runbook > Missing in ledger'."""
    title = fallback_title
    title_found = False
    stack: list[tuple[int, str]] = []
    sections: list[Section] = []
    lines: list[str] = []
    heading: str | None = None
    in_code = False

    def flush() -> None:
        body = "\n".join(lines).strip()
        if body:
            sections.append(Section(body, heading))
        lines.clear()

    for line in text.splitlines():
        if _FENCE.match(line):
            in_code = not in_code
        match = None if in_code else _HEADING.match(line)  # a "#" inside code is not a heading
        if match is None:
            lines.append(line)
            continue
        flush()
        level, name = len(match.group(1)), match.group(2)
        if level == 1 and not title_found:
            title, title_found = name, True
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, name))
        heading = " > ".join(item[1] for item in stack)
    flush()
    return ParsedDocument(title, tuple(sections))


def _parse_text(text: str, fallback_title: str) -> ParsedDocument:
    body = text.strip()
    return ParsedDocument(fallback_title, (Section(body),) if body else ())


def _parse_pdf(data: bytes, fallback_title: str) -> ParsedDocument:
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise DocumentLoadError("the PDF is encrypted")
        sections = []
        for number, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if text:
                sections.append(Section(text, None, number))
    except PyPdfError as error:
        raise DocumentLoadError(f"the PDF could not be read: {error}") from None
    if not sections:
        raise DocumentLoadError("the PDF has no extractable text (a scanned PDF needs OCR first)")
    return ParsedDocument(fallback_title, tuple(sections))


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")  # also removes the invisible marker Excel/Word add
    except UnicodeDecodeError:
        raise DocumentLoadError("the file is not valid UTF-8 text") from None


def parse_document(data: bytes, filename: str) -> ParsedDocument:
    """Read a Markdown, text or PDF file. Anything else is refused with a clear message."""
    path = PurePath(filename)
    suffix, stem = path.suffix.lower(), path.stem
    if suffix not in SUPPORTED:
        raise DocumentLoadError(
            f"unsupported file type {suffix or '(none)'}; supported: {', '.join(SUPPORTED)}"
        )
    if suffix == ".pdf":
        document = _parse_pdf(data, stem)
    elif suffix == ".txt":
        document = _parse_text(_decode(data), stem)
    else:
        document = _parse_markdown(_decode(data), stem)
    if not document.sections:
        raise DocumentLoadError("the document is empty")
    return document
