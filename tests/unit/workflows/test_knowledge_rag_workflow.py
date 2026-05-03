from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.exceptions import AppException
from backend.models.orm.knowledge import FileStatus
from backend.workflow.knowledge_rag_workflow import KnowledgeRAGWorkflow


class FakeChunkingService:
    def __init__(self, chunk_size: int = 10):
        self.chunk_size = chunk_size
        self.split_calls: list[tuple[str, str]] = []

    def split_text(self, text: str, file_suffix: str = ".txt") -> list[dict]:
        self.split_calls.append((text, file_suffix))
        if len(text) <= self.chunk_size:
            return [{"content": text, "chunk_index": 0}]
        return [
            {"content": text[: self.chunk_size], "chunk_index": 0},
            {"content": text[self.chunk_size :], "chunk_index": 1},
        ]


def make_workflow(chunking_service: FakeChunkingService) -> KnowledgeRAGWorkflow:
    return KnowledgeRAGWorkflow(
        knowledge_service=MagicMock(),
        chunking_service=chunking_service,
        vector_index_service=MagicMock(),
    )


def test_extract_chunks_uses_plain_text_channel(tmp_path):
    chunking = FakeChunkingService(chunk_size=10)
    workflow = make_workflow(chunking)
    file_path = tmp_path / "demo.txt"
    file_path.write_text("plain content", encoding="utf-8")

    chunks = workflow._extract_chunks(file_path)

    assert [chunk["content"] for chunk in chunks] == ["plain cont", "ent"]
    assert chunking.split_calls == [("plain content", ".txt")]


def test_extract_chunks_uses_lightweight_pdf_channel(monkeypatch, tmp_path):
    chunking = FakeChunkingService(chunk_size=10)
    workflow = make_workflow(chunking)
    file_path = tmp_path / "demo.pdf"
    file_path.write_text("fake", encoding="utf-8")

    class FakeTextPage:
        def __init__(self, text: str):
            self.text = text

        def get_text_range(self) -> str:
            return self.text

        def close(self) -> None:
            pass

    class FakePage:
        def __init__(self, text: str):
            self.text = text

        def get_textpage(self) -> FakeTextPage:
            return FakeTextPage(self.text)

        def close(self) -> None:
            pass

    class FakePdfDocument:
        def __init__(self, _: object):
            self.pages = [FakePage("0123456789ABC"), FakePage("short")]

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def __len__(self) -> int:
            return len(self.pages)

        def __getitem__(self, index: int) -> FakePage:
            return self.pages[index]

    monkeypatch.setattr(
        "backend.workflow.knowledge_rag_workflow.pdfium.PdfDocument",
        FakePdfDocument,
    )

    chunks = workflow._extract_chunks(file_path)

    assert [chunk["content"] for chunk in chunks] == ["0123456789", "ABC", "short"]
    assert [chunk["page_label"] for chunk in chunks] == ["1", "1", "2"]
    assert chunking.split_calls == [("0123456789ABC", ".txt"), ("short", ".txt")]


def test_prepare_chunks_for_index_adds_contextual_embedding_content():
    chunks = [
        {
            "content": "body",
            "section_path": "Intro / Setup",
            "chunk_index": 0,
        },
        {
            "content": "page body",
            "page_label": "2",
            "chunk_index": 1,
        },
    ]

    prepared = KnowledgeRAGWorkflow._prepare_chunks_for_index(
        chunks=chunks,
        filename="demo.md",
        file_path="s3://bucket/demo.md",
    )

    assert prepared[0]["content"] == "body"
    assert prepared[0]["meta_info"]["section_path"] == "Intro / Setup"
    assert prepared[0]["meta_info"]["source_path"] == "s3://bucket/demo.md"
    assert prepared[0]["embedding_content"] == (
        "[文档: demo.md] [章节: Intro / Setup]\nbody"
    )
    assert prepared[1]["meta_info"]["page_label"] == "2"
    assert prepared[1]["embedding_content"] == "[文档: demo.md] [页码: 2]\npage body"


def test_extract_chunks_rejects_docx_without_structured_parser(tmp_path):
    chunking = FakeChunkingService()
    workflow = make_workflow(chunking)
    file_path = tmp_path / "demo.docx"
    file_path.write_text("fake", encoding="utf-8")

    with pytest.raises(AppException):
        workflow._extract_chunks(file_path)


def test_extract_chunks_rejects_unsupported_file_suffix(tmp_path):
    chunking = FakeChunkingService()
    workflow = make_workflow(chunking)
    file_path = tmp_path / "demo.bin"
    file_path.write_text("fake", encoding="utf-8")

    with pytest.raises(AppException):
        workflow._extract_chunks(file_path)


class FakeAsyncUow:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None


class FakeStorage:
    def __init__(self, path):
        self.path = path

    @asynccontextmanager
    async def download_to_temp(self, _file_obj):
        yield self.path


@pytest.mark.asyncio
async def test_ingest_file_downloads_from_storage_before_extracting(tmp_path):
    file_path = tmp_path / "downloaded.txt"
    file_path.write_text("remote content", encoding="utf-8")
    file_obj = SimpleNamespace(
        id="file-id",
        kb_id="kb-id",
        filename="demo.txt",
        file_path="s3://bucket/key",
        file_size=14,
        storage_backend="s3",
        storage_bucket="bucket",
        storage_key="key",
    )
    statuses = []

    async def set_file_status(*, file_id, status):
        statuses.append(status)
        if status == FileStatus.PARSING:
            return file_obj
        return file_obj

    knowledge_service = SimpleNamespace(
        uow=FakeAsyncUow(),
        storage=FakeStorage(file_path),
        set_file_status=set_file_status,
    )
    vector_index_service = SimpleNamespace(
        uow=FakeAsyncUow(),
        replace_file_chunks=AsyncMock(),
    )
    chunking = FakeChunkingService(chunk_size=20)
    workflow = KnowledgeRAGWorkflow(
        knowledge_service=knowledge_service,
        chunking_service=chunking,
        vector_index_service=vector_index_service,
    )

    await workflow.ingest_file(file_id="file-id")

    vector_index_service.replace_file_chunks.assert_called_once_with(
        file_id="file-id",
        chunks=[
            {
                "content": "remote content",
                "chunk_index": 0,
                "meta_info": {
                    "filename": "demo.txt",
                    "path": "s3://bucket/key",
                    "source_path": "s3://bucket/key",
                },
                "embedding_content": "[文档: demo.txt]\nremote content",
            }
        ],
        filename="demo.txt",
        file_path="s3://bucket/key",
    )
    assert statuses == [FileStatus.PARSING, FileStatus.CHUNKING, FileStatus.READY]
