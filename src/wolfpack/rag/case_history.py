"""Case-history RAG pipeline.

Indexes closed-case summaries from the learning queue.
Retrieval is **semantic-dominant** (alpha=0.7) — cosine similarity
over pgvector embeddings is the primary signal, with keyword
search as a fallback / tie-breaker.
"""

from __future__ import annotations

from typing import Any

import asyncpg

from wolfpack.rag.base import OllamaEmbedder, PGVectorStore, RAGDocument, RAGPipeline


class CaseHistoryPipeline(RAGPipeline):
    """RAG pipeline for historical closed-case summaries.

    Args:
        pool: asyncpg connection pool.
        embedder: Ollama embedding client.  If ``None`` the pipeline
            falls back to keyword-only retrieval.
    """

    TABLE_NAME = "wolfpack_rag_case_history"
    VECTOR_DIM = 768  # nomic-embed-text

    def __init__(
        self,
        pool: asyncpg.Pool,
        embedder: OllamaEmbedder | None = None,
    ) -> None:
        self._store = PGVectorStore(
            pool=pool,
            table_name=self.TABLE_NAME,
            vector_dim=self.VECTOR_DIM,
            embedder=embedder,
        )

    async def ensure_schema(self) -> None:
        await self._store.ensure_schema()

    async def index(self, documents: list[RAGDocument]) -> None:
        await self._store.write_documents(documents)

    async def ingest_case_summary(self, summary: Any) -> None:
        """Index a structured case summary into case-history RAG.

        The *narrative* field is used for semantic search, while remaining
        fields become filterable metadata.  Duplicate ``case_id`` entries
        update the existing record (upsert).
        """
        from wolfpack.learning.summary import CaseSummary

        if not isinstance(summary, CaseSummary):
            summary = CaseSummary.model_validate(summary)
        doc = RAGDocument(
            id=summary.case_id,
            content=summary.narrative,
            metadata=summary.to_rag_document()["metadata"],
        )
        await self._store.write_documents([doc])

    async def retrieve(
        self,
        query: str,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[RAGDocument]:
        """Hybrid retrieval: semantic-dominant (alpha=0.7).

        Fetches ``top_k * 2`` candidates from each modality, then
        re-ranks by a weighted combination of normalised scores.
        """
        candidates: list[tuple[RAGDocument, float, str]] = []

        # Semantic search (primary)
        semantic_results: list[RAGDocument] = []
        if self._store._embedder is not None:
            semantic_results = await self._store.query_by_text(
                query, top_k=top_k * 2, filters=filters
            )
        for rank, doc in enumerate(semantic_results):
            score = 1.0 - (rank / max(len(semantic_results), 1))
            candidates.append((doc, score, "semantic"))

        # Keyword search (fallback / tie-breaker)
        keyword_results = await self._store.keyword_search(
            query, top_k=top_k * 2, filters=filters
        )
        for rank, doc in enumerate(keyword_results):
            score = 1.0 - (rank / max(len(keyword_results), 1))
            candidates.append((doc, score, "keyword"))

        # Deduplicate by id and fuse scores additively
        fused: dict[str, tuple[RAGDocument, float]] = {}
        for doc, score, modality in candidates:
            alpha = 0.7 if modality == "semantic" else 0.3
            if doc.id in fused:
                existing_doc, existing_score = fused[doc.id]
                fused[doc.id] = (existing_doc, existing_score + score * alpha)
            else:
                fused[doc.id] = (doc, score * alpha)

        ranked = sorted(fused.values(), key=lambda x: x[1], reverse=True)
        return [doc for doc, _ in ranked[:top_k]]
