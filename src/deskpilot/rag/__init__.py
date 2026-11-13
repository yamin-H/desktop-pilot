from deskpilot.rag.chunker import Chunk, Section, chunk_sections
from deskpilot.rag.embedder import (
    EMBEDDING_DIMENSION,
    Embedder,
    EmbeddingError,
    FastEmbedEmbedder,
    HashingEmbedder,
)
from deskpilot.rag.ingest import IngestResult, ingest_directory, ingest_file
from deskpilot.rag.loader import DocumentLoadError, ParsedDocument, parse_document
from deskpilot.rag.search import Hit, fuse, hybrid_search
from deskpilot.rag.store import (
    DocumentInfo,
    DocumentStore,
    EmbeddedChunk,
    RawHit,
    or_query,
    vector_literal,
)

__all__ = [
    "EMBEDDING_DIMENSION",
    "Chunk",
    "DocumentInfo",
    "DocumentLoadError",
    "DocumentStore",
    "EmbeddedChunk",
    "Embedder",
    "EmbeddingError",
    "FastEmbedEmbedder",
    "HashingEmbedder",
    "Hit",
    "IngestResult",
    "ParsedDocument",
    "RawHit",
    "Section",
    "chunk_sections",
    "fuse",
    "hybrid_search",
    "ingest_directory",
    "ingest_file",
    "or_query",
    "parse_document",
    "vector_literal",
]
