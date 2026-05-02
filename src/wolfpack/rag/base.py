"""RAG pipeline base interface and pgvector helpers.

Provides an async-native abstraction over Haystack Document types and
pgvector similarity search, backed by Ollama for embeddings.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import Any

import asyncpg
import httpx
from haystack.dataclasses import Document
from pydantic import BaseModel, Field

from wolfpack.config.settings import LLMConfig


class RAGDocument(BaseModel):
    """Serializable document for indexing and retrieval."""

    id: str = Field(..., description="Unique document identifier.")
    content: str = Field(..., description="Text content to embed and search.")
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_haystack(cls, doc: Document) -> RAGDocument:
        return cls(
            id=doc.id or "",
            content=doc.content or "",
            metadata=doc.meta or {},
        )

    def to_haystack(self) -> Document:
        return Document(id=self.id, content=self.content, meta=self.metadata)


class RAGPipeline(ABC):
    """Async-native RAG pipeline interface.

    Implementations handle embedding generation, vector storage,
    and hybrid/semantic retrieval.
    """

    @abstractmethod
    async def index(self, documents: list[RAGDocument]) -> None:
        """Index documents into the vector store."""

    @abstractmethod
    async def retrieve(
        self,
        query: str,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[RAGDocument]:
        """Retrieve the top-k most relevant documents for *query*."""


class OllamaEmbedder:
    """Async Ollama embedding client."""

    def __init__(
        self,
        base_url: str,
        model: str = "nomic-embed-text",
        timeout_s: float = 60.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout_s

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Return embedding vectors for *texts* via Ollama /api/embed."""
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._base_url}/api/embed",
                json={"model": self._model, "input": texts},
            )
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
            embeddings: list[Any] = data.get("embeddings", [])
            # Ollama returns list of vectors when input is a list
            if embeddings and isinstance(embeddings[0], list):
                return [list(map(float, emb)) for emb in embeddings]
            # Single vector fallback
            if embeddings:
                return [list(map(float, embeddings))]
            return []

    @classmethod
    def from_llm_config(cls, cfg: LLMConfig) -> OllamaEmbedder:
        """Build embedder from LLM config (assumes Ollama provider)."""
        return cls(
            base_url=cfg.base_url,
            model="nomic-embed-text",
            timeout_s=cfg.request_timeout_s,
        )


class PGVectorStore:
    """Async pgvector document store using raw SQL.

    Creates a table with a ``vector`` column and supports cosine-similarity
    search.  The schema is namespaced per pipeline via *table_name*.
    """

    # Allowlist of safe table name characters: alphanumeric and underscore only
    _TABLE_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
    # Allowlist of safe filter key characters: alphanumeric, underscore, hyphen, dot
    _FILTER_KEY_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_.\-]*$")
    _ALLOWED_TABLES: frozenset[str] = frozenset()

    def __init__(
        self,
        pool: asyncpg.Pool,
        table_name: str,
        vector_dim: int = 768,
        embedder: OllamaEmbedder | None = None,
        allowed_tables: frozenset[str] | None = None,
    ) -> None:
        if allowed_tables is not None:
            PGVectorStore._ALLOWED_TABLES = allowed_tables
        if PGVectorStore._ALLOWED_TABLES and table_name not in PGVectorStore._ALLOWED_TABLES:
            raise ValueError(f"table_name {table_name!r} not in allowlist")
        if not self._TABLE_NAME_RE.match(table_name):
            raise ValueError(f"table_name contains invalid characters: {table_name!r}")
        self._pool = pool
        self._table = table_name
        self._vector_dim = vector_dim
        self._embedder = embedder

    async def ensure_schema(self) -> None:
        """Create the table and vector index if they do not exist."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._table} (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    metadata JSONB DEFAULT '{{}}',
                    embedding VECTOR({self._vector_dim})
                )
                """
            )
            await conn.execute(
                f"""
                CREATE INDEX IF NOT EXISTS {self._table}_embedding_idx
                ON {self._table}
                USING ivfflat (embedding vector_cosine_ops)
                """
            )

    @staticmethod
    def _format_vector(vec: list[float]) -> str:
        """Format a float list as a pgvector literal string."""
        return "[" + ",".join(str(v) for v in vec) + "]"

    async def write_documents(self, documents: list[RAGDocument]) -> None:
        """Embed and insert documents."""
        if not documents:
            return
        embeddings: list[list[float]] = []
        if self._embedder is not None:
            texts = [doc.content for doc in documents]
            embeddings = await self._embedder.embed(texts)
        else:
            embeddings = [[0.0] * self._vector_dim for _ in documents]
        async with self._pool.acquire() as conn:
            for doc, emb in zip(documents, embeddings, strict=True):
                _sql = (
                    f"""
                    INSERT INTO {self._table} (id, content, metadata, embedding)
                    VALUES ($1, $2, $3, $4::vector)
                    ON CONFLICT (id) DO UPDATE SET
                        content = EXCLUDED.content,
                        metadata = EXCLUDED.metadata,
                        embedding = EXCLUDED.embedding
                    """  # noqa: S608
                )
                await conn.execute(
                    _sql,
                    doc.id,
                    doc.content,
                    json.dumps(doc.metadata),
                    self._format_vector(emb),
                )

    async def query_by_embedding(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[RAGDocument]:
        """Cosine-similarity search over the vector column."""
        where_clause = ""
        params: list[Any] = [self._format_vector(query_embedding), top_k]
        if filters:
            conditions = []
            for key, value in filters.items():
                if not self._FILTER_KEY_RE.match(key):
                    raise ValueError(f"Invalid filter key: {key!r}")
                conditions.append(f"metadata->>'{key}' = ${len(params) + 1}")
                params.append(value)
            where_clause = "WHERE " + " AND ".join(conditions)

        async with self._pool.acquire() as conn:
            _sql = (
                f"""
                SELECT id, content, metadata,
                       1 - (embedding <=> $1::vector) AS score
                FROM {self._table}
                {where_clause}
                ORDER BY embedding <=> $1::vector
                LIMIT $2
                """  # noqa: S608
            )
            rows = await conn.fetch(_sql, *params)
        return [
            RAGDocument(
                id=row["id"],
                content=row["content"],
                metadata=(
                    json.loads(row["metadata"])
                    if isinstance(row["metadata"], str)
                    else (row["metadata"] or {})
                ),
            )
            for row in rows
        ]

    async def query_by_text(
        self,
        query: str,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[RAGDocument]:
        """Embed *query* and run similarity search."""
        if self._embedder is None:
            return []
        embeddings = await self._embedder.embed([query])
        if not embeddings:
            return []
        return await self.query_by_embedding(
            embeddings[0], top_k=top_k, filters=filters
        )

    async def keyword_search(
        self,
        query: str,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[RAGDocument]:
        """Full-text search using Postgres tsvector (fallback when no embedding)."""
        where_clause = ""
        params: list[Any] = [query, top_k]
        if filters:
            conditions = []
            for key, value in filters.items():
                if not self._FILTER_KEY_RE.match(key):
                    raise ValueError(f"Invalid filter key: {key!r}")
                conditions.append(f"metadata->>'{key}' = ${len(params) + 1}")
                params.append(value)
            where_clause = "WHERE " + " AND ".join(conditions)

        async with self._pool.acquire() as conn:
            _sql = (
                f"""
                SELECT id, content, metadata,
                       ts_rank(
                           to_tsvector('english', content),
                           plainto_tsquery('english', $1)
                       ) AS score
                FROM {self._table}
                {where_clause}
                ORDER BY score DESC
                LIMIT $2
                """  # noqa: S608
            )
            rows = await conn.fetch(_sql, *params)
        return [
            RAGDocument(
                id=row["id"],
                content=row["content"],
                metadata=(
                    json.loads(row["metadata"])
                    if isinstance(row["metadata"], str)
                    else (row["metadata"] or {})
                ),
            )
            for row in rows
        ]
