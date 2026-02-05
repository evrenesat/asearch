"""Embedding client for LM Studio (OpenAI-compatible API)."""

import logging
import struct
from typing import List, Optional

import requests

from asky.config import (
    RESEARCH_EMBEDDING_API_URL,
    RESEARCH_EMBEDDING_MODEL,
    RESEARCH_EMBEDDING_TIMEOUT,
    RESEARCH_EMBEDDING_BATCH_SIZE,
)

logger = logging.getLogger(__name__)


class EmbeddingClient:
    """Client for local embedding API (LM Studio / OpenAI-compatible)."""

    _instance: Optional["EmbeddingClient"] = None

    def __new__(cls, *args, **kwargs):
        """Singleton pattern for efficient reuse."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(
        self,
        api_url: str = None,
        model: str = None,
        timeout: int = None,
        batch_size: int = None,
    ):
        # Skip re-initialization for singleton
        if self._initialized:
            return

        self.api_url = api_url or RESEARCH_EMBEDDING_API_URL
        self.model = model or RESEARCH_EMBEDDING_MODEL
        self.timeout = timeout or RESEARCH_EMBEDDING_TIMEOUT
        self.batch_size = batch_size or RESEARCH_EMBEDDING_BATCH_SIZE
        self._initialized = True

        logger.debug(
            f"EmbeddingClient initialized: url={self.api_url}, model={self.model}"
        )

    def embed(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a list of texts.

        Automatically batches requests if needed.
        """
        if not texts:
            return []

        # Filter out empty texts
        texts = [t for t in texts if t and t.strip()]
        if not texts:
            return []

        all_embeddings = []

        # Process in batches
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            batch_embeddings = self._embed_batch(batch)
            all_embeddings.extend(batch_embeddings)

        return all_embeddings

    def _embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a single batch."""
        try:
            response = requests.post(
                self.api_url,
                json={"input": texts, "model": self.model},
                timeout=self.timeout,
            )
            response.raise_for_status()

            data = response.json()

            # Handle different response formats
            if "data" in data:
                # OpenAI format
                embeddings = [item["embedding"] for item in data["data"]]
            elif "embeddings" in data:
                # Alternative format
                embeddings = data["embeddings"]
            else:
                raise ValueError(f"Unexpected response format: {list(data.keys())}")

            return embeddings

        except requests.exceptions.ConnectionError:
            logger.error(
                f"Failed to connect to embedding API at {self.api_url}. "
                "Is LM Studio running with an embedding model loaded?"
            )
            raise
        except requests.exceptions.Timeout:
            logger.error(
                f"Embedding API request timed out after {self.timeout}s"
            )
            raise
        except Exception as e:
            logger.error(f"Embedding API error: {e}")
            raise

    def embed_single(self, text: str) -> List[float]:
        """Generate embedding for a single text."""
        if not text or not text.strip():
            raise ValueError("Cannot embed empty text")
        result = self.embed([text])
        return result[0] if result else []

    def is_available(self) -> bool:
        """Check if the embedding API is available."""
        try:
            # Try a simple embedding request
            self.embed_single("test")
            return True
        except Exception:
            return False

    @staticmethod
    def serialize_embedding(embedding: List[float]) -> bytes:
        """Convert embedding to bytes for SQLite storage.

        Uses float32 format (4 bytes per float).
        """
        return struct.pack(f"{len(embedding)}f", *embedding)

    @staticmethod
    def deserialize_embedding(data: bytes) -> List[float]:
        """Convert bytes back to embedding list."""
        if not data:
            return []
        count = len(data) // 4  # 4 bytes per float32
        return list(struct.unpack(f"{count}f", data))


def get_embedding_client() -> EmbeddingClient:
    """Get the singleton embedding client instance."""
    return EmbeddingClient()
