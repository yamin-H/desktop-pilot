import asyncio
import hashlib
from dataclasses import dataclass
from pathlib import Path

from deskpilot.rag.chunker import Chunk, chunk_sections
from deskpilot.rag.embedder import EMBEDDING_DIMENSION, Embedder, EmbeddingError
from deskpilot.rag.loader import SUPPORTED, DocumentLoadError, parse_document
from deskpilot.rag.store import DocumentStore, EmbeddedChunk

# Bump this when the way we chunk or embed changes, to re-ingest everything.
PIPELINE_VERSION = 1


@dataclass(frozen=True)
class IngestResult:
    source: str
    status: str  # added, updated, unchanged, failed or removed
    chunks: int = 0
    error: str | None = None


def embedding_text(chunk: Chunk) -> str:
    """What gets embedded: the heading helps a chunk be found for its topic."""
    return f"{chunk.heading}\n{chunk.text}" if chunk.heading else chunk.text


def _fingerprint(data: bytes, max_chars: int, overlap: int, embedder: Embedder) -> str:
    settings = f"|v{PIPELINE_VERSION}|{max_chars}|{overlap}|{embedder.name}"
    return hashlib.sha256(data + settings.encode()).hexdigest()


async def ingest_file(
    store: DocumentStore,
    embedder: Embedder,
    path: Path,
    *,
    root: Path,
    max_chars: int = 1000,
    overlap: int = 150,
) -> IngestResult:
    """Load, chunk, embed and store one file. Unchanged files are skipped."""
    if embedder.dimension != EMBEDDING_DIMENSION:
        raise EmbeddingError(
            f"embedder {embedder.name} has {embedder.dimension} dimensions, "
            f"the database expects {EMBEDDING_DIMENSION}"
        )
    source = path.relative_to(root).as_posix()
    try:
        data = path.read_bytes()
    except OSError as error:
        return IngestResult(source, "failed", error=f"cannot read the file: {error}")

    fingerprint = _fingerprint(data, max_chars, overlap, embedder)
    existing = await store.get_hash(source)
    if existing == fingerprint:
        return IngestResult(source, "unchanged")

    try:
        parsed = parse_document(data, path.name)
    except DocumentLoadError as error:
        return IngestResult(source, "failed", error=str(error))
    chunks = chunk_sections(parsed.sections, max_chars=max_chars, overlap=overlap)

    # Embedding is the slow part, so it happens outside the database transaction.
    vectors = await asyncio.to_thread(embedder.embed, [embedding_text(c) for c in chunks])
    embedded = [EmbeddedChunk(c, v) for c, v in zip(chunks, vectors, strict=True)]
    await store.replace_document(source, parsed.title, fingerprint, embedded)
    return IngestResult(source, "updated" if existing else "added", len(chunks))


async def ingest_directory(
    store: DocumentStore,
    embedder: Embedder,
    directory: Path,
    *,
    prune: bool = False,
    max_chars: int = 1000,
    overlap: int = 150,
) -> list[IngestResult]:
    """Ingest every supported file under `directory` (hidden files and folders are skipped).

    With `prune`, documents in the library whose file is no longer there are removed.
    A bad file is reported as failed and never stops the others.
    """
    files = sorted(
        path
        for path in directory.rglob("*")
        if path.is_file()
        and path.suffix.lower() in SUPPORTED
        and not any(part.startswith(".") for part in path.relative_to(directory).parts)
    )
    results = [
        await ingest_file(
            store, embedder, path, root=directory, max_chars=max_chars, overlap=overlap
        )
        for path in files
    ]
    if prune:
        present = {result.source for result in results}
        for info in await store.list_documents():
            if info.source not in present:
                await store.delete_document(info.source)
                results.append(IngestResult(info.source, "removed"))
    return results
