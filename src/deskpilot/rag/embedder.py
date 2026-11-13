import hashlib
import math
import re
import threading
from collections.abc import Sequence
from typing import Any, Protocol

EMBEDDING_DIMENSION = 384  # must match the vector(384) column
DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"

_TOKEN = re.compile(r"[a-z0-9]+")


class EmbeddingError(Exception):
    """The embedder cannot be used with our database."""


class Embedder(Protocol):
    """Turns texts into vectors of numbers that capture their meaning."""

    name: str
    dimension: int

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class HashingEmbedder:
    """A tiny stand-in for tests: texts sharing words get similar vectors. No model needed.

    It only understands shared WORDS, not meaning, so it is for testing the plumbing, never
    for judging search quality.
    """

    name = "hashing-384"
    dimension = EMBEDDING_DIMENSION

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._one(text) for text in texts]

    def _one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        for token in _TOKEN.findall(text.lower()):
            digest = hashlib.sha256(token.encode()).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            vector[index] += 1.0 if digest[4] % 2 == 0 else -1.0
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:  # no words at all: use a fixed direction, never an all-zero vector
            vector[0] = 1.0
            return vector
        return [value / norm for value in vector]


class FastEmbedEmbedder:
    """The real embedder: a small model running on this machine (fastembed, ONNX).

    The model is loaded on first use, and downloaded then if it is not on disk yet.
    """

    def __init__(self, model_name: str = DEFAULT_MODEL, dimension: int = EMBEDDING_DIMENSION):
        self.name = model_name
        self.dimension = dimension
        self._model: Any = None
        self._lock = threading.Lock()

    def _load(self) -> Any:
        with self._lock:
            if self._model is None:
                from fastembed import TextEmbedding  # imported late: it is slow to load

                self._model = TextEmbedding(model_name=self.name)
            return self._model

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        model = self._load()
        vectors = [[float(value) for value in vector] for vector in model.embed(list(texts))]
        for vector in vectors:
            if len(vector) != self.dimension:
                raise EmbeddingError(
                    f"model {self.name} produced {len(vector)} numbers per text, "
                    f"but the database expects {self.dimension}"
                )
        return vectors
