"""Shared fixtures and helpers for tests/unit/workflows/.

职责：提供 workflows 测试复用的 FakeAsyncUow、fake_chat_uow、make_rag_hit；
边界：不 import backend.main，不启动 HTTP stack 或真实外部依赖；副作用：无。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest


class FakeAsyncUow:
    """Minimal async UoW context manager with empty repos."""

    async def __aenter__(self) -> FakeAsyncUow:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return


class FakeChatUow:
    """Async UoW with chat_repo and user_repo AsyncMocks."""

    def __init__(self) -> None:
        self.chat_repo = AsyncMock()
        self.user_repo = AsyncMock()

    async def __aenter__(self) -> FakeChatUow:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return


@pytest.fixture
def fake_async_uow() -> FakeAsyncUow:
    return FakeAsyncUow()


@pytest.fixture
def fake_chat_uow() -> FakeChatUow:
    return FakeChatUow()


def make_rag_hit(
    *,
    content: str = "worker-side context",
    index: int = 0,
    score: float | None = None,
    distance: float | None = None,
) -> dict:
    _score = 0.9 - index * 0.1 if score is None else score
    _distance = 0.1 + index * 0.1 if distance is None else distance
    return {
        "id": str(uuid.uuid4()),
        "content": content,
        "source_type": "file",
        "file_id": str(uuid.uuid4()),
        "message_id": None,
        "filename": f"doc-{index}.md",
        "chunk_index": index,
        "meta_info": {},
        "distance": _distance,
        "score": _score,
    }
