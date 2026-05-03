"""Knowledge RAG ingestion workflow.

职责：下载已上传文件、解析文本、切片并替换向量索引。
边界：本模块不保存上传文件、不创建任务；上传和任务投递由 KnowledgeUploadWorkflow 负责。
失败处理：解析或索引失败会把文件状态标记为 FAILED。
"""

import asyncio
import uuid
from pathlib import Path
from typing import cast

import pypdfium2 as pdfium

from backend.core.exceptions import (
    AppException,
    app_not_found,
    app_service_error,
    app_validation_error,
)
from backend.models.orm.knowledge import FileStatus
from backend.observability.trace_utils import set_span_attributes, trace_span
from backend.services.chunking_service import ChunkingService, ChunkPayload
from backend.services.knowledge_service import KnowledgeService
from backend.services.vector_index_service import VectorIndexService

TEXT_FILE_SUFFIXES = {
    ".txt",
    ".md",
    ".markdown",
    ".csv",
    ".json",
    ".jsonl",
    ".yaml",
    ".yml",
    ".log",
    ".py",
    ".sql",
}

PDF_FILE_SUFFIXES = {".pdf"}


class KnowledgeRAGWorkflow:
    """知识文件入库编排器。"""

    def __init__(
        self,
        knowledge_service: KnowledgeService,
        chunking_service: ChunkingService,
        vector_index_service: VectorIndexService,
    ) -> None:
        self.knowledge_service = knowledge_service
        self.chunking_service = chunking_service
        self.vector_index_service = vector_index_service

    async def ingest_file(
        self,
        *,
        file_id: uuid.UUID,
    ) -> None:
        with trace_span("knowledge.ingest.load_file", {"rag.file_id": file_id}) as span:
            async with self.knowledge_service.uow:
                file_obj = await self.knowledge_service.set_file_status(
                    file_id=file_id,
                    status=FileStatus.PARSING,
                )
            if file_obj:
                set_span_attributes(
                    span,
                    {
                        "rag.kb_id": file_obj.kb_id,
                        "file.name": file_obj.filename,
                        "file.path": file_obj.file_path,
                        "file.storage_backend": file_obj.storage_backend,
                        "file.storage_key": file_obj.storage_key,
                        "file.size": file_obj.file_size,
                    },
                )
        if not file_obj:
            raise app_not_found("文件不存在", code="KNOWLEDGE_FILE_NOT_FOUND")

        try:
            async with self.knowledge_service.storage.download_to_temp(
                file_obj
            ) as file_path:
                with trace_span(
                    "knowledge.ingest.extract_chunks",
                    {
                        "rag.file_id": file_id,
                        "rag.kb_id": file_obj.kb_id,
                        "file.name": file_obj.filename,
                        "file.extension": file_path.suffix.lower(),
                        "file.storage_backend": file_obj.storage_backend,
                    },
                ) as span:
                    chunks = await asyncio.to_thread(self._extract_chunks, file_path)
                    chunks = self._prepare_chunks_for_index(
                        chunks=chunks,
                        filename=file_obj.filename,
                        file_path=file_obj.file_path,
                    )
                    set_span_attributes(span, {"rag.chunk_count": len(chunks)})
            if not chunks:
                raise app_validation_error(
                    "文件无可用文本内容，无法构建 RAG 索引",
                    code="KNOWLEDGE_FILE_NO_TEXT",
                )

            with trace_span(
                "knowledge.ingest.index_chunks",
                {
                    "rag.file_id": file_id,
                    "rag.kb_id": file_obj.kb_id,
                    "rag.chunk_count": len(chunks),
                },
            ):
                async with self.knowledge_service.uow:
                    await self.knowledge_service.set_file_status(
                        file_id=file_id,
                        status=FileStatus.CHUNKING,
                    )
                async with self.vector_index_service.uow:
                    await self.vector_index_service.replace_file_chunks(
                        file_id=file_id,
                        chunks=chunks,
                        filename=file_obj.filename,
                        file_path=file_obj.file_path,
                    )
                async with self.knowledge_service.uow:
                    await self.knowledge_service.set_file_status(
                        file_id=file_id,
                        status=FileStatus.READY,
                    )
        except FileNotFoundError as exc:
            async with self.knowledge_service.uow:
                await self.knowledge_service.set_file_status(
                    file_id=file_id,
                    status=FileStatus.FAILED,
                )
            raise app_not_found(
                "上传文件在存储路径中不存在",
                code="KNOWLEDGE_FILE_OBJECT_NOT_FOUND",
            ) from exc
        except AppException:
            async with self.knowledge_service.uow:
                await self.knowledge_service.set_file_status(
                    file_id=file_id,
                    status=FileStatus.FAILED,
                )
            raise
        except Exception as exc:
            async with self.knowledge_service.uow:
                await self.knowledge_service.set_file_status(
                    file_id=file_id,
                    status=FileStatus.FAILED,
                )
            raise app_service_error(
                "知识文件处理失败，请稍后重试",
                code="KNOWLEDGE_FILE_INGEST_FAILED",
            ) from exc

    def _extract_chunks(self, file_path: Path) -> list[ChunkPayload]:
        suffix = file_path.suffix.lower()
        if suffix in TEXT_FILE_SUFFIXES:
            return self._extract_text_chunks(file_path)
        if suffix in PDF_FILE_SUFFIXES:
            return self._extract_pdf_chunks(file_path)

        raise app_validation_error(
            f"暂不支持的文件类型: {suffix or '(无扩展名)'}，建议使用 txt/md/pdf",
            code="KNOWLEDGE_FILE_UNSUPPORTED_TYPE",
        )

    def _extract_text_chunks(self, file_path: Path) -> list[ChunkPayload]:
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        return self.chunking_service.split_text(text, file_suffix=file_path.suffix)

    def _extract_pdf_chunks(self, file_path: Path) -> list[ChunkPayload]:
        try:
            chunks: list[ChunkPayload] = []
            for page_text, page_label in self._extract_pdf_text_by_page(file_path):
                page_chunks = self.chunking_service.split_text(
                    page_text,
                    file_suffix=".txt",
                )
                for chunk in page_chunks:
                    chunk["page_label"] = page_label
                    chunks.append(chunk)
            return chunks
        except AppException:
            raise
        except Exception as exc:
            raise app_validation_error(
                f"文件解析失败: {file_path.name}",
                code="KNOWLEDGE_FILE_PARSE_FAILED",
            ) from exc

    @staticmethod
    def _extract_pdf_text_by_page(file_path: Path) -> list[tuple[str, str]]:
        page_texts: list[tuple[str, str]] = []
        with pdfium.PdfDocument(file_path) as document:
            for page_index in range(len(document)):
                page = document[page_index]
                text_page = None
                try:
                    text_page = page.get_textpage()
                    text = text_page.get_text_range().strip()
                    if text:
                        page_texts.append((text, str(page_index + 1)))
                finally:
                    if text_page is not None:
                        text_page.close()
                    page.close()
        return page_texts

    @staticmethod
    def _prepare_chunks_for_index(
        *,
        chunks: list[ChunkPayload],
        filename: str,
        file_path: str,
    ) -> list[ChunkPayload]:
        prepared_chunks: list[ChunkPayload] = []
        for chunk in chunks:
            content = chunk["content"]
            meta_info = {
                **(chunk.get("meta_info") or {}),
                "filename": filename,
                "path": file_path,
                "source_path": file_path,
            }
            section_path = chunk.get("section_path")
            page_label = chunk.get("page_label")
            if section_path:
                meta_info["section_path"] = section_path
            if page_label:
                meta_info["page_label"] = page_label

            prepared = dict(chunk)
            prepared["content"] = content
            prepared["meta_info"] = meta_info
            prepared["embedding_content"] = "\n".join(
                [
                    KnowledgeRAGWorkflow._build_context_prefix(
                        filename=filename,
                        section_path=section_path,
                        page_label=page_label,
                    ),
                    content,
                ]
            ).strip()
            prepared_chunks.append(cast(ChunkPayload, prepared))
        return prepared_chunks

    @staticmethod
    def _build_context_prefix(
        *,
        filename: str,
        section_path: str | None = None,
        page_label: str | None = None,
    ) -> str:
        parts = [f"[文档: {filename}]"]
        if section_path:
            parts.append(f"[章节: {section_path}]")
        if page_label:
            parts.append(f"[页码: {page_label}]")
        return " ".join(parts)
