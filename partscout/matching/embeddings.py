# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
from abc import ABC, abstractmethod

import httpx

logger = logging.getLogger(__name__)

_VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"
_BATCH_SIZE = 128


class EmbeddingClient(ABC):
    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts. Returns one vector per text."""

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]


class VoyageClient(EmbeddingClient):
    """Voyage AI embeddings — voyage-3 produces 1024-dim vectors."""

    def __init__(self, api_key: str, model: str = "voyage-3") -> None:
        self._api_key = api_key
        self._model = model
        self._http = httpx.Client(timeout=60)

    def embed(self, texts: list[str]) -> list[list[float]]:
        results: list[list[float]] = []
        for i in range(0, len(texts), _BATCH_SIZE):
            batch = texts[i : i + _BATCH_SIZE]
            resp = self._http.post(
                _VOYAGE_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={"model": self._model, "input": batch},
            )
            resp.raise_for_status()
            data = resp.json()
            ordered = sorted(data["data"], key=lambda x: x["index"])
            batch_vecs = [item["embedding"] for item in ordered]
            results.extend(batch_vecs)
            logger.debug(
                "Voyage embed: model=%s batch=%d tokens=%s",
                self._model,
                len(batch),
                data.get("usage", {}).get("total_tokens"),
            )
        return results


class OpenAICompatibleEmbeddingClient(EmbeddingClient):
    """Works with any /v1/embeddings endpoint (Ollama, Gemini, etc.)."""

    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        self._model = model
        self._url = base_url.rstrip("/") + "/embeddings"
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        self._http = httpx.Client(timeout=60)

    def embed(self, texts: list[str]) -> list[list[float]]:
        results: list[list[float]] = []
        for i in range(0, len(texts), _BATCH_SIZE):
            batch = texts[i : i + _BATCH_SIZE]
            resp = self._http.post(
                self._url,
                headers=self._headers,
                json={"model": self._model, "input": batch},
            )
            resp.raise_for_status()
            data = resp.json()
            ordered = sorted(data["data"], key=lambda x: x["index"])
            batch_vecs = [item["embedding"] for item in ordered]
            results.extend(batch_vecs)
        return results


def build_embedding_client(
    provider: str,
    model: str,
    api_key: str,
    base_url: str | None = None,
) -> EmbeddingClient:
    if provider == "voyage":
        return VoyageClient(api_key=api_key, model=model)
    if provider == "openai_compatible":
        if not base_url:
            raise ValueError("base_url required for openai_compatible embedding provider")
        return OpenAICompatibleEmbeddingClient(api_key=api_key, base_url=base_url, model=model)
    raise ValueError(f"Unknown embedding provider: {provider!r}")
