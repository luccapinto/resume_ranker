"""Embedding providers (local / OpenAI / Voyage) behind one interface.

Dense vectors come from the configured provider; the sparse "lexical" vector is
always produced locally by a hashed bag-of-terms, so exact technical tokens keep
working regardless of which dense backend is in use.

Providers are cached at module level — building a `SentenceTransformer` costs
seconds, and this used to happen on every request.
"""

from __future__ import annotations

import hashlib
import math
import re
import threading
from abc import ABC, abstractmethod
from typing import Dict, List, Optional

import httpx

from api import observability as obs
from api.config import settings

_STOPWORDS = {
    "de", "da", "do", "das", "dos", "e", "a", "o", "as", "os", "um", "uma", "em",
    "no", "na", "nos", "nas", "para", "por", "com", "que", "se", "ao", "à", "the",
    "of", "and", "to", "in", "for", "with", "on", "at", "is",
}


class EmbeddingProvider(ABC):
    @abstractmethod
    def get_dense_embedding(self, text: str) -> List[float]:
        """Dense semantic vector for a single text."""

    @abstractmethod
    def get_sparse_embedding(self, text: str) -> Dict[int, float]:
        """Sparse lexical vector: {term_hash: weight}."""

    @property
    @abstractmethod
    def dimension(self) -> int: ...

    @property
    def name(self) -> str:
        return self.__class__.__name__

    def get_dense_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Batch helper; providers override when they support real batching."""
        return [self.get_dense_embedding(t) for t in texts]


def _local_sparse_tokenize(text: str) -> Dict[int, float]:
    """Hashed, sub-linear TF weighting over normalised tokens."""
    if not text:
        return {}
    normalized = re.sub(r"[^\w\s\-\+#]", " ", text.lower().strip())
    tokens = [t for t in normalized.split() if t and t not in _STOPWORDS and len(t) > 1]
    if not tokens:
        return {}

    counts: Dict[str, int] = {}
    for token in tokens:
        counts[token] = counts.get(token, 0) + 1

    return {
        int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16) % 1_000_000: 1.0 + math.log(count)
        for token, count in counts.items()
    }


class LocalEmbeddingProvider(EmbeddingProvider):
    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name or settings.EMBEDDING_MODEL_LOCAL
        self._model = None
        self._lock = threading.Lock()

    @property
    def model(self):
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from sentence_transformers import SentenceTransformer

                    self._model = SentenceTransformer(self.model_name)
        return self._model

    @property
    def name(self) -> str:
        return f"local:{self.model_name}"

    @property
    def dimension(self) -> int:
        # Renamed in sentence-transformers 6; keep working on both.
        getter = getattr(self.model, "get_embedding_dimension", None) or (
            self.model.get_sentence_embedding_dimension
        )
        return getter()

    def get_dense_embedding(self, text: str) -> List[float]:
        if not text:
            return [0.0] * self.dimension
        return self.model.encode(text).tolist()

    def get_dense_embeddings(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        with obs.span("embed.batch", kind=obs.KIND_EMBEDDING, count=len(texts), model=self.model_name):
            return [v.tolist() for v in self.model.encode(texts)]

    def get_sparse_embedding(self, text: str) -> Dict[int, float]:
        return _local_sparse_tokenize(text)


class _HTTPEmbeddingProvider(EmbeddingProvider):
    """Shared plumbing for the OpenAI-compatible embedding APIs."""

    url: str = ""
    provider_label: str = "http"

    def __init__(self, api_key: str, model_name: str, dimension: int):
        self.api_key = api_key
        self.model_name = model_name
        self._dimension = dimension

    @property
    def name(self) -> str:
        return f"{self.provider_label}:{self.model_name}"

    @property
    def dimension(self) -> int:
        return self._dimension

    def _post(self, payload: dict) -> dict:
        if not self.api_key:
            raise ValueError(
                f"{self.provider_label} API key não configurada para embeddings."
            )
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                self.url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        if response.status_code != 200:
            raise ValueError(f"{self.provider_label} embeddings error: {response.text[:400]}")
        return response.json()

    def get_dense_embedding(self, text: str) -> List[float]:
        if not text:
            return [0.0] * self._dimension
        with obs.span("embed.remote", kind=obs.KIND_EMBEDDING, model=self.model_name):
            data = self._post({"input": text, "model": self.model_name})
            return data["data"][0]["embedding"]

    def get_dense_embeddings(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        with obs.span(
            "embed.remote.batch", kind=obs.KIND_EMBEDDING, model=self.model_name, count=len(texts)
        ):
            data = self._post({"input": texts, "model": self.model_name})
            return [item["embedding"] for item in data["data"]]

    def get_sparse_embedding(self, text: str) -> Dict[int, float]:
        return _local_sparse_tokenize(text)


class OpenAIEmbeddingProvider(_HTTPEmbeddingProvider):
    url = "https://api.openai.com/v1/embeddings"
    provider_label = "openai"

    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        super().__init__(
            api_key or settings.OPENAI_API_KEY,
            model_name or settings.EMBEDDING_MODEL_OPENAI,
            1536,
        )


class VoyageEmbeddingProvider(_HTTPEmbeddingProvider):
    url = "https://api.voyageai.com/v1/embeddings"
    provider_label = "voyage"

    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        super().__init__(
            api_key or settings.VOYAGE_API_KEY,
            model_name or settings.EMBEDDING_MODEL_VOYAGE,
            1024,
        )


_provider_cache: Dict[str, EmbeddingProvider] = {}
_provider_lock = threading.Lock()


def get_embedding_provider() -> EmbeddingProvider:
    """Return the configured provider, built once per process."""
    key = settings.EMBEDDING_PROVIDER.lower()
    provider = _provider_cache.get(key)
    if provider is None:
        with _provider_lock:
            provider = _provider_cache.get(key)
            if provider is None:
                if key == "openai":
                    provider = OpenAIEmbeddingProvider()
                elif key == "voyage":
                    provider = VoyageEmbeddingProvider()
                else:
                    provider = LocalEmbeddingProvider()
                _provider_cache[key] = provider
    return provider
