"""Vector index service.

职责：把文件切片转换为 embedding 并写入/检索知识库索引。
边界：本模块不解析原始文件、不决定知识库访问权限。
风险：替换文件切片会先删除旧索引再写入新索引，调用方应放在事务边界内。
"""

import asyncio
import hashlib
import uuid
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from typing import Literal, NotRequired, TypedDict

from backend.utils.token_estimation import count_tokens
from backend.contracts.interfaces import AbstractRAGEmbedder, AbstractUnitOfWork
from backend.models.orm.chunk import ChunkSourceType, DocumentChunk
from backend.observability.trace_utils import set_span_attributes, trace_span
from backend.services.base import BaseService
from backend.services.chunking_service import ChunkPayload
from backend.utils.search_text import build_search_texts, normalize_query

CHUNKING_VERSION = 2


class _HybridHit(TypedDict):
    """混合检索融合过程中的内部命中结构。"""

    chunk: DocumentChunk
    score: float
    matched_by: set[str]


class RetrievalHit(TypedDict):
    """RAG 检索结果和分数语义。"""

    chunk: DocumentChunk
    distance: float
    retrieval_mode: Literal["vector", "fulltext", "hybrid"]
    score_kind: str
    raw_score: float | None
    evidence_score: float
    matched_by: NotRequired[list[str]]


class _IndexChunk(TypedDict):
    content: str
    embedding_content: str
    meta_info: dict[str, object]


class PreparedChunkRecord(TypedDict):
    source_type: ChunkSourceType
    file_id: uuid.UUID
    content: str
    search_text: str
    content_hash: str
    token_count: int
    chunk_index: int
    chunking_version: int
    meta_info: dict[str, object]
    embedding: list[float]


class VectorIndexService(BaseService[AbstractUnitOfWork]):
    """知识库向量索引写入和检索服务。"""

    def __init__(
        self,
        uow: AbstractUnitOfWork,
        embedder: AbstractRAGEmbedder,
        embed_batch_size: int = 32,
        read_uow_factory: Callable[[], AbstractUnitOfWork] | None = None,
    ) -> None:
        super().__init__(uow)
        self.embedder = embedder
        self.embed_batch_size = max(1, embed_batch_size)
        self._read_uow_factory = read_uow_factory

    @asynccontextmanager
    async def _read_repo(self) -> AsyncIterator:
        read_uow = self._read_uow_factory() if self._read_uow_factory else self.uow
        async with read_uow.read_context():
            yield read_uow.knowledge_repo

    async def replace_file_chunks(
        self,
        *,
        file_id: uuid.UUID,
        chunks: Sequence[str | ChunkPayload],
        filename: str,
        file_path: str,
    ) -> None:
        with trace_span(
            "vector_index.replace_file_chunks",
            {
                "rag.file_id": file_id,
                "rag.filename": filename,
                "rag.chunk_count": len(chunks),
                "embedding.batch_size": self.embed_batch_size,
            },
        ) as span:
            chunk_records = await self.prepare_chunk_records(
                file_id=file_id,
                chunks=chunks,
                filename=filename,
                file_path=file_path,
            )

            await self.uow.knowledge_repo.delete_chunks_for_file(file_id=file_id)
            await self.uow.knowledge_repo.add_chunks(
                [dict(record) for record in chunk_records]
            )
            set_span_attributes(
                span,
                {
                    "rag.indexed_chunk_count": len(chunk_records),
                    "embedding.output_dim": len(chunk_records[0]["embedding"])
                    if chunk_records
                    else None,
                },
            )

    async def prepare_chunk_records(
        self,
        *,
        file_id: uuid.UUID,
        chunks: Sequence[str | ChunkPayload],
        filename: str,
        file_path: str,
    ) -> list[PreparedChunkRecord]:
        chunk_records: list[PreparedChunkRecord] = []
        for start in range(0, len(chunks), self.embed_batch_size):
            batch = [
                self._normalize_chunk(
                    chunk,
                    filename=filename,
                    file_path=file_path,
                )
                for chunk in chunks[start : start + self.embed_batch_size]
            ]
            batch_records = await self._prepare_chunk_record_batch(
                file_id=file_id,
                chunks=batch,
                start_index=start,
            )
            chunk_records.extend(batch_records)
        return chunk_records

    async def _prepare_chunk_record_batch(
        self,
        *,
        file_id: uuid.UUID,
        chunks: Sequence[_IndexChunk],
        start_index: int,
    ) -> list[PreparedChunkRecord]:
        embedding_inputs = [chunk["embedding_content"] for chunk in chunks]
        embeddings = await self.embedder.encode_documents(embedding_inputs)
        if len(embeddings) != len(chunks):
            raise ValueError("RAG embedding 批量返回数量与输入切片数量不一致")
        search_texts = await asyncio.to_thread(
            build_search_texts,
            [chunk["content"] for chunk in chunks],
        )

        records: list[PreparedChunkRecord] = []
        for offset, (chunk, embedding, search_text) in enumerate(
            zip(chunks, embeddings, search_texts, strict=True)
        ):
            content = chunk["content"]
            embedding_content = chunk["embedding_content"]
            records.append(
                {
                    "source_type": ChunkSourceType.FILE,
                    "file_id": file_id,
                    "content": content,
                    "search_text": search_text,
                    "content_hash": hashlib.sha256(
                        embedding_content.encode("utf-8")
                    ).hexdigest(),
                    "token_count": count_tokens(content),
                    "chunk_index": start_index + offset,
                    "chunking_version": CHUNKING_VERSION,
                    "meta_info": chunk["meta_info"],
                    "embedding": embedding,
                }
            )
        return records

    @staticmethod
    def _normalize_chunk(
        chunk: str | ChunkPayload,
        *,
        filename: str,
        file_path: str,
    ) -> _IndexChunk:
        if isinstance(chunk, str):
            content = chunk
            embedding_content = chunk
            meta_info: dict[str, object] = {}
        else:
            content = chunk["content"]
            embedding_content = chunk.get("embedding_content") or content
            meta_info = dict(chunk.get("meta_info") or {})
            for key in ("section_path", "page_label", "source_path"):
                value = chunk.get(key)
                if value:
                    meta_info.setdefault(key, value)

        meta_info.setdefault("filename", filename)
        meta_info.setdefault("path", file_path)
        return {
            "content": content,
            "embedding_content": embedding_content,
            "meta_info": meta_info,
        }

    async def search_chunks_for_kb(
        self,
        *,
        query_text: str,
        kb_id: uuid.UUID,
        limit: int,
    ) -> list[RetrievalHit]:
        if not query_text.strip() or limit <= 0:
            return []

        with trace_span(
            "vector_index.search.vector",
            {
                "rag.kb_id": kb_id,
                "rag.top_k": limit,
                "rag.query.char_count": len(query_text),
            },
        ) as span:
            query_vector = await self.embedder.encode_query(query_text)
            async with self._read_repo() as repo:
                hits = await repo.search_chunks_for_kb(
                    query_vector=query_vector,
                    kb_id=kb_id,
                    limit=limit,
                )
            set_span_attributes(
                span,
                {
                    "embedding.query_dim": len(query_vector),
                    "rag.hit_count": len(hits),
                },
            )
            return [
                self._build_retrieval_hit(
                    chunk=chunk,
                    distance=distance,
                    retrieval_mode="vector",
                    score_kind="vector_similarity",
                    raw_score=max(0.0, 1.0 - distance),
                    evidence_score=max(0.0, 1.0 - distance),
                    matched_by=["vector"],
                )
                for chunk, distance in hits
            ]

    async def search_chunks_for_kb_fulltext(
        self,
        *,
        query_text: str,
        kb_id: uuid.UUID,
        limit: int,
    ) -> list[RetrievalHit]:
        if not query_text.strip() or limit <= 0:
            return []

        with trace_span(
            "vector_index.search.fulltext",
            {
                "rag.kb_id": kb_id,
                "rag.top_k": limit,
                "rag.query.char_count": len(query_text),
            },
        ) as span:
            normalized_query = await asyncio.to_thread(normalize_query, query_text)
            if not normalized_query:
                set_span_attributes(span, {"rag.hit_count": 0})
                return []
            async with self._read_repo() as repo:
                hits = await repo.search_chunks_for_kb_fulltext(
                    normalized_query=normalized_query,
                    kb_id=kb_id,
                    limit=limit,
                )
            set_span_attributes(span, {"rag.hit_count": len(hits)})
            return [
                self._build_retrieval_hit(
                    chunk=chunk,
                    distance=self._rank_to_distance(rank),
                    retrieval_mode="fulltext",
                    score_kind="fulltext_rank_similarity",
                    raw_score=rank,
                    evidence_score=max(0.0, 1.0 - self._rank_to_distance(rank)),
                    matched_by=["fulltext"],
                )
                for chunk, rank in hits
            ]

    async def search_chunks_for_kb_hybrid(
        self,
        *,
        query_text: str,
        kb_id: uuid.UUID,
        limit: int,
        vector_weight: float = 0.7,
        fulltext_weight: float = 0.3,
        candidate_multiplier: int = 4,
    ) -> list[RetrievalHit]:
        if not query_text.strip() or limit <= 0:
            return []

        with trace_span(
            "vector_index.search.hybrid",
            {
                "rag.kb_id": kb_id,
                "rag.top_k": limit,
                "rag.query.char_count": len(query_text),
                "rag.vector_weight": vector_weight,
                "rag.fulltext_weight": fulltext_weight,
            },
        ) as span:
            query_vector, normalized_query = await asyncio.gather(
                self.embedder.encode_query(query_text),
                asyncio.to_thread(normalize_query, query_text),
            )
            candidate_limit = limit * max(1, candidate_multiplier)

            async with self._read_repo() as repo:
                vector_hits = await repo.search_chunks_for_kb(
                    query_vector=query_vector,
                    kb_id=kb_id,
                    limit=candidate_limit,
                )
                if normalized_query:
                    fulltext_hits = await repo.search_chunks_for_kb_fulltext(
                        normalized_query=normalized_query,
                        kb_id=kb_id,
                        limit=candidate_limit,
                    )
                else:
                    fulltext_hits = []

            hits = self._fuse_hybrid_hits(
                vector_hits=vector_hits,
                fulltext_hits=fulltext_hits,
                limit=limit,
                vector_weight=vector_weight,
                fulltext_weight=fulltext_weight,
            )
            set_span_attributes(
                span,
                {
                    "embedding.query_dim": len(query_vector),
                    "rag.candidate_limit": candidate_limit,
                    "rag.vector_hit_count": len(vector_hits),
                    "rag.fulltext_hit_count": len(fulltext_hits),
                    "rag.hit_count": len(hits),
                },
            )
            return hits

    @staticmethod
    def _fuse_hybrid_hits(
        *,
        vector_hits: list[tuple[DocumentChunk, float]],
        fulltext_hits: list[tuple[DocumentChunk, float]],
        limit: int,
        vector_weight: float,
        fulltext_weight: float,
    ) -> list[RetrievalHit]:
        if not vector_hits and not fulltext_hits:
            return []

        rrf_k = 60.0
        fused: dict[str, _HybridHit] = {}

        for rank, (chunk, _) in enumerate(vector_hits, start=1):
            key = str(chunk.id)
            item = fused.setdefault(
                key,
                {"chunk": chunk, "score": 0.0, "matched_by": set()},
            )
            item["score"] = float(item["score"]) + vector_weight / (rrf_k + rank)
            item["matched_by"].add("vector")

        for rank, (chunk, _) in enumerate(fulltext_hits, start=1):
            key = str(chunk.id)
            item = fused.setdefault(
                key,
                {"chunk": chunk, "score": 0.0, "matched_by": set()},
            )
            item["score"] = float(item["score"]) + fulltext_weight / (rrf_k + rank)
            item["matched_by"].add("fulltext")

        ranked = sorted(
            fused.values(),
            key=lambda item: float(item["score"]),
            reverse=True,
        )[:limit]
        if not ranked:
            return []

        best_possible_score = (vector_weight + fulltext_weight) / (rrf_k + 1)
        if best_possible_score <= 0:
            return [
                VectorIndexService._build_retrieval_hit(
                    chunk=item["chunk"],
                    distance=1.0,
                    retrieval_mode="hybrid",
                    score_kind="hybrid_relative_rrf",
                    raw_score=float(item["score"]),
                    evidence_score=0.0,
                    matched_by=sorted(item["matched_by"]),
                )
                for item in ranked
            ]

        # RRF 分数用于排序；evidence_score 按理论最大值归一化，避免 top1 天然满分。
        return [
            VectorIndexService._build_retrieval_hit(
                chunk=item["chunk"],
                distance=max(0.0, 1.0 - (float(item["score"]) / best_possible_score)),
                retrieval_mode="hybrid",
                score_kind="hybrid_relative_rrf",
                raw_score=float(item["score"]),
                evidence_score=max(
                    0.0,
                    min(1.0, float(item["score"]) / best_possible_score),
                ),
                matched_by=sorted(item["matched_by"]),
            )
            for item in ranked
        ]

    @staticmethod
    def _rank_to_distance(rank: float) -> float:
        return 1.0 / (1.0 + max(0.0, rank))

    @staticmethod
    def _build_retrieval_hit(
        *,
        chunk: DocumentChunk,
        distance: float,
        retrieval_mode: Literal["vector", "fulltext", "hybrid"],
        score_kind: str,
        raw_score: float | None,
        evidence_score: float,
        matched_by: list[str],
    ) -> RetrievalHit:
        return {
            "chunk": chunk,
            "distance": distance,
            "retrieval_mode": retrieval_mode,
            "score_kind": score_kind,
            "raw_score": raw_score,
            "evidence_score": evidence_score,
            "matched_by": matched_by,
        }
