"""Embedding providers.

An embedding turns text into a list of numbers so that texts with similar meaning
end up close together. Questions and document chunks go through the same model,
then the closest chunks are retrieved.
"""

import hashlib
import math
import re
from functools import lru_cache

from langchain_core.embeddings import Embeddings

from app.core.config import settings

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    "a an and are as at be by for from has have how in is it its of on or that the this to "
    "was were what when where which who why will with does do did can".split()
)


class HashEmbeddings(Embeddings):
    """A tiny keyword-based embedding that needs no model download.

    Each word is hashed into one of `dimensions` slots ("the hashing trick"), and the
    vector is normalised to length 1. It only matches shared words, not meaning, so it
    is used for the automated tests and for a zero-install demo -- not for real use.
    """

    def __init__(self, dimensions: int = 512):
        self.dimensions = dimensions

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in _TOKEN_RE.findall(text.lower()):
            if token in _STOPWORDS:
                continue
            digest = hashlib.md5(token.encode()).digest()  # stable across runs, unlike hash()
            slot = int.from_bytes(digest[:4], "little") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[slot] += sign
        norm = math.sqrt(sum(v * v for v in vector))
        return [v / norm for v in vector] if norm else vector

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


def embedding_model_name() -> str:
    """Identifier stored with every chunk, e.g. 'ollama:nomic-embed-text'.

    Vectors from different models cannot be compared, so search only looks at chunks
    whose model matches the one currently configured.
    """
    provider = settings.EMBEDDING_PROVIDER.lower()
    if provider == "ollama":
        return f"ollama:{settings.OLLAMA_EMBEDDING_MODEL}"
    if provider == "huggingface":
        return f"huggingface:{settings.HUGGINGFACE_EMBEDDING_MODEL}"
    if provider == "hash":
        return f"hash:{settings.HASH_EMBEDDING_DIMENSIONS}"
    raise ValueError(f"Unknown EMBEDDING_PROVIDER: {settings.EMBEDDING_PROVIDER}")


@lru_cache(maxsize=4)
def _build(model_name: str, base_url: str) -> Embeddings:
    provider, _, model = model_name.partition(":")
    if provider == "ollama":
        from langchain_ollama import OllamaEmbeddings

        return OllamaEmbeddings(model=model, base_url=base_url)
    if provider == "huggingface":
        try:
            from langchain_huggingface import HuggingFaceEmbeddings
        except ImportError as exc:  # optional dependency
            raise RuntimeError(
                "Hugging Face embeddings are not installed. Run `uv sync --extra huggingface`."
            ) from exc
        return HuggingFaceEmbeddings(model_name=model)
    return HashEmbeddings(dimensions=int(model))


def get_embeddings() -> Embeddings:
    return _build(embedding_model_name(), settings.OLLAMA_BASE_URL)
