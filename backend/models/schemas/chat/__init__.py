"""Chat schema package — re-exports for backward compatibility.

职责：聚合 chat 子模块的公开类型，保持旧 import 路径可用。
边界：本模块不定义任何新类型，只做 re-export。
"""

from backend.models.schemas.chat.api import (
    ChatQueryResponse,
    MessageResponse,
    QuerySentRequest,
    SessionDetailResponse,
    SessionListResponse,
    SessionResponse,
    SessionUpdateRequest,
)
from backend.models.schemas.chat.commands import ChatQueryCommand
from backend.models.schemas.chat.dto import (
    ChatMessageRole,
    ConversationMessage,
    LLMQueryDTO,
    LLMResultDTO,
    MessageRole,
    MessageStatusEnum,
)
from backend.models.schemas.chat.params import LLMExtraBody, LLMThinkingConfig
from backend.models.schemas.chat.payloads import GenerationPayload, GenerationResult

__all__ = [
    "ChatMessageRole",
    "ChatQueryCommand",
    "ChatQueryResponse",
    "ConversationMessage",
    "GenerationPayload",
    "GenerationResult",
    "LLMExtraBody",
    "LLMQueryDTO",
    "LLMResultDTO",
    "LLMThinkingConfig",
    "MessageResponse",
    "MessageRole",
    "MessageStatusEnum",
    "QuerySentRequest",
    "SessionDetailResponse",
    "SessionListResponse",
    "SessionResponse",
    "SessionUpdateRequest",
]
