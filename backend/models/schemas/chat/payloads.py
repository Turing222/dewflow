"""Worker payload schemas.

职责：定义 Web → Worker 任务投递的数据契约。
边界：必须完全可 JSON 序列化，且 Web 和 Worker 共同引用此模块，不依赖具体实现。
"""

import uuid
from typing import Any

from pydantic import BaseModel, Field

from backend.models.schemas.chat.context_state import ContextState
from backend.models.schemas.chat.dto import ConversationMessage


class GenerationPayload(BaseModel):
    """Worker payload for LLM generation tasks."""

    session_id: uuid.UUID
    query_text: str
    conversation_history: list[ConversationMessage] = Field(default_factory=list)
    kb_id: uuid.UUID | None = None
    rag_candidates: list[dict[str, Any]] = Field(default_factory=list)
    context_state: ContextState = Field(default_factory=ContextState)
    enable_external_context: bool = False
    billing_model_name: str = "default"
    extra_body: dict[str, object] | None = None


class GenerationResult(BaseModel):
    """Worker → Web non-stream task result."""

    success: bool
    content: str = ""
    tokens_input: int | None = None
    tokens_output: int | None = None
    search_context: dict | None = None
    latency_ms: int | None = None
    error: str | None = None


class LLMTaskPayload(BaseModel):
    """Unified LLM generation TaskIQ payload (v2 wire format)."""

    generation_payload: dict[str, Any]
    channel: str | None = None
    trace_context: dict[str, str] | None = None
    assistant_message_id: str | None = None
    user_id: str | None = None
    idempotency_lock_key: str | None = None

    model_config = {"extra": "forbid"}
