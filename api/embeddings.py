import os
import re
import hashlib
import math
from typing import List, Dict
from abc import ABC, abstractmethod
import httpx
from api.config import settings

class EmbeddingProvider(ABC):
    @abstractmethod
    def get_dense_embedding(self, text: str) -> List[float]:
        """Generate dense embedding for the given text."""
        pass

    @abstractmethod
    def get_sparse_embedding(self, text: str) -> Dict[int, float]:
        """Generate sparse embedding for lexical search."""
        pass

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Return the dimension of dense embeddings."""
        pass

def _local_sparse_tokenize(text: str) -> Dict[int, float]:
    """Helper function to generate sparse vectors locally for exact term matching."""
    if not text:
        return {}
    # Convert to lowercase and replace most punctuation with spaces, keeping technical terms intact
    normalized = text.lower().strip()
    normalized = re.sub(r'[^\w\s\-\+#]', ' ', normalized)
    tokens = [t for t in normalized.split() if t]
    if not tokens:
        return {}
    
    counts = {}
    for token in tokens:
        counts[token] = counts.get(token, 0) + 1
        
    sparse_vector = {}
    for token, count in counts.items():
        # Stable hash to a range [0, 999999]
        token_hash = int(hashlib.md5(token.encode('utf-8')).hexdigest(), 16) % 1000000
        sparse_vector[token_hash] = float(1.0 + math.log(count))
    return sparse_vector

class LocalEmbeddingProvider(EmbeddingProvider):
    def __init__(self, model_name: str = None):
        self.model_name = model_name or settings.EMBEDDING_MODEL_LOCAL
        self._model = None

    @property
    def model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name)
        return self._model

    @property
    def dimension(self) -> int:
        return self.model.get_sentence_embedding_dimension()

    def get_dense_embedding(self, text: str) -> List[float]:
        if not text:
            return [0.0] * self.dimension
        embedding = self.model.encode(text)
        return embedding.tolist()

    def get_sparse_embedding(self, text: str) -> Dict[int, float]:
        return _local_sparse_tokenize(text)

class OpenAIEmbeddingProvider(EmbeddingProvider):
    def __init__(self, api_key: str = None, model_name: str = None):
        self.api_key = api_key or settings.OPENAI_API_KEY
        self.model_name = model_name or settings.EMBEDDING_MODEL_OPENAI
        self._dimension = 1536  # text-embedding-3-small default

    @property
    def dimension(self) -> int:
        return self._dimension

    def get_dense_embedding(self, text: str) -> List[float]:
        if not text:
            return [0.0] * self._dimension
        
        if not self.api_key:
            raise ValueError("OpenAI API Key not configured. Please set OPENAI_API_KEY environment variable.")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "input": text,
            "model": self.model_name
        }
        with httpx.Client(timeout=15.0) as client:
            response = client.post("https://api.openai.com/v1/embeddings", headers=headers, json=payload)
            if response.status_code != 200:
                raise ValueError(f"OpenAI API returned error: {response.text}")
            data = response.json()
            return data["data"][0]["embedding"]

    def get_sparse_embedding(self, text: str) -> Dict[int, float]:
        return _local_sparse_tokenize(text)

class VoyageEmbeddingProvider(EmbeddingProvider):
    def __init__(self, api_key: str = None, model_name: str = None):
        self.api_key = api_key or settings.VOYAGE_API_KEY
        self.model_name = model_name or settings.EMBEDDING_MODEL_VOYAGE
        self._dimension = 1024  # voyage-multilingual-2 default

    @property
    def dimension(self) -> int:
        return self._dimension

    def get_dense_embedding(self, text: str) -> List[float]:
        if not text:
            return [0.0] * self._dimension
        
        if not self.api_key:
            raise ValueError("Voyage API Key not configured. Please set VOYAGE_API_KEY environment variable.")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "input": text,
            "model": self.model_name
        }
        with httpx.Client(timeout=15.0) as client:
            response = client.post("https://api.voyageai.com/v1/embeddings", headers=headers, json=payload)
            if response.status_code != 200:
                raise ValueError(f"Voyage API returned error: {response.text}")
            data = response.json()
            return data["data"][0]["embedding"]

    def get_sparse_embedding(self, text: str) -> Dict[int, float]:
        return _local_sparse_tokenize(text)

def get_embedding_provider() -> EmbeddingProvider:
    provider = settings.EMBEDDING_PROVIDER.lower()
    if provider == "openai":
        return OpenAIEmbeddingProvider()
    elif provider == "voyage":
        return VoyageEmbeddingProvider()
    else:
        return LocalEmbeddingProvider()
