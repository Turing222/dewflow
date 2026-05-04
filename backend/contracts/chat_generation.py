"""Shared chat generation payload contracts.

This module is intentionally lightweight so Web workflows can build worker
payloads without importing worker-side AI orchestration.

职责：定义 Web → Worker 任务投递的数据契约。
边界：不依赖 worker 侧 AI 编排模块，Web 和 Worker 共同引用此模块。
"""

import uuid
from typing import Any

from pydantic import BaseModel, Field

from backend.models.schemas.chat_schema import ConversationMessage


class GenerationPayload(BaseModel):
    """Worker payload for LLM generation tasks."""

    session_id: uuid.UUID
    query_text: str
    conversation_history: list[ConversationMessage] = Field(default_factory=list)
    kb_id: uuid.UUID | None = None
    rag_candidates: list[dict[str, Any]] = Field(default_factory=list)
