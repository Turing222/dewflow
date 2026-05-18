"""Internal service DTOs.

职责：定义内部服务之间传递的数据传输对象。
边界：不包含 HTTP 请求/响应逻辑，也不包含 worker 持久化逻辑。
"""

import uuid
from typing import TypedDict

from pydantic import BaseModel, Field


class ConversationMessage(TypedDict):
    """内部对话消息格式，在 provider 边界层再转换为具体 SDK schema。"""

    role: str
    content: str


class LLMQueryDTO(BaseModel):
    """传递给 LLM provider 的查询参数。"""

    session_id: uuid.UUID
    query_text: str
    conversation_history: list[ConversationMessage] = Field(default_factory=list)
    extra_body: dict[str, object] | None = None


class LLMResultDTO(BaseModel):
    """LLM provider 返回的结果。"""

    content: str
    latency_ms: int | None = None
    success: bool = True
    error_message: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
