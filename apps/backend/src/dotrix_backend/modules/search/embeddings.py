"""Embedding models for the search index: text -> a vector of EMBEDDING_DIMENSIONS numbers.

Set with DOTRIX_EMBEDDING_MODEL ("provider:model", using that provider's API key). Without a
model or its key, search still works on keywords alone.
"""
from __future__ import annotations

import logging
from typing import Any, Protocol

from dotrix_backend.core.settings import Settings

from .models import EMBEDDING_DIMENSIONS

logger = logging.getLogger(__name__)

# Roughly four characters per token: for usage logs (the providers don't report it here).
CHARS_PER_TOKEN = 4


class Embedder(Protocol):
    model: str
    min_similarity: float  # meaning matches below this cosine similarity don't count

    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


class LangchainEmbedder:
    """A langchain embeddings model for documents, and one set up for queries (Gemini ranks
    better when told which is which)."""

    def __init__(self, model: str, documents: Any, queries: Any, min_similarity: float) -> None:
        self.model = model
        self.min_similarity = min_similarity
        self._documents, self._queries = documents, queries

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self._documents.aembed_documents(texts)

    async def embed_query(self, text: str) -> list[float]:
        return await self._queries.aembed_query(text)


def build_embedder(settings: Settings) -> Embedder | None:
    """The configured embedding model, or None (keyword search only)."""
    spec = (settings.embedding_model or "").strip()
    if not spec:
        return None
    provider, _, name = spec.partition(":")
    if provider == "google_genai":
        key = settings.google_api_key
        if key is None or not key.get_secret_value().strip():
            logger.warning("search: no GOOGLE_API_KEY for %s; searching by keywords only", spec)
            return None
        from langchain_google_genai import GoogleGenerativeAIEmbeddings

        def gemini(task: str) -> Any:
            return GoogleGenerativeAIEmbeddings(
                model=name,
                google_api_key=key,
                task_type=task,
                output_dimensionality=EMBEDDING_DIMENSIONS,
            )

        return LangchainEmbedder(
            spec, gemini("RETRIEVAL_DOCUMENT"), gemini("RETRIEVAL_QUERY"), settings.embedding_min_similarity
        )
    if provider == "openai":
        key = settings.openai_api_key
        if key is None or not key.get_secret_value().strip():
            logger.warning("search: no OPENAI_API_KEY for %s; searching by keywords only", spec)
            return None
        from langchain_openai import OpenAIEmbeddings

        model = OpenAIEmbeddings(model=name, api_key=key, dimensions=EMBEDDING_DIMENSIONS)
        return LangchainEmbedder(spec, model, model, settings.embedding_min_similarity)
    logger.warning("search: embedding model %r isn't supported (google_genai or openai); keywords only", spec)
    return None
