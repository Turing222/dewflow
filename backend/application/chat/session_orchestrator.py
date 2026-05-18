"""Shared web chat request preparation.

职责：复用 Web 流式和非流式聊天的幂等、会话、消息和 payload 准备流程。
边界：本模块不序列化 HTTP/SSE 响应，也不消费 Worker 流式结果。
失败处理：准备阶段失败由调用方按 stream/non-stream 协议转换响应。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

import redis.asyncio as redis

from backend.application.chat.history_projection import history_to_conversation_messages
from backend.config.settings import settings
from backend.contracts.interfaces import AbstractUnitOfWork
from backend.core.concurrency import db_concurrency_slot
from backend.core.exceptions import app_validation_error
from backend.infra.redis import safe_release_lock
from backend.models.schemas.chat.commands import ChatQueryCommand
from backend.models.schemas.chat.payloads import GenerationPayload
from backend.observability.trace_utils import set_span_attributes, trace_span
from backend.services.chat_service import SessionManager
from backend.services.knowledge_service import DEFAULT_KNOWLEDGE_BASE_NAME
from backend.services.permission_service import PermissionService

if TYPE_CHECKING:
    from backend.models.orm.chat import ChatMessage, ChatSession


@dataclass(frozen=True, slots=True)
class ChatIdempotencyState:
    """一次聊天请求的幂等锁状态。"""

    lock_key: str | None
    lock_token: str | None
    is_new: bool
    value: str | None

    @property
    def is_processing_duplicate(self) -> bool:
        return self.value is not None and self.value.startswith("processing:")


@dataclass(slots=True)
class ChatPreparedRequest:
    """Web workflow 投递 Worker 前所需的共享上下文。"""

    session: ChatSession
    assistant_message: ChatMessage
    generation_payload: GenerationPayload
    lock_key: str | None
    lock_token: str | None
    trace_attrs: dict[str, object]


class ChatSessionOrchestrator:
    """准备 Web 聊天请求的共享编排器。"""

    def __init__(
        self,
        uow: AbstractUnitOfWork,
        redis_client: redis.Redis,
        permission_service: PermissionService,
        session_manager: SessionManager | None = None,
    ) -> None:
        self.uow = uow
        self.redis = redis_client
        self.permission_service = permission_service
        self._session_manager = session_manager or SessionManager(
            uow, permission_service
        )

    async def check_idempotency(
        self,
        *,
        command: ChatQueryCommand,
        trace_attrs: dict[str, object],
        span_name: str,
    ) -> ChatIdempotencyState:
        lock_key: str | None = None
        lock_token: str | None = None
        value: str | None = None
        is_new = True

        with trace_span(span_name, trace_attrs) as span:
            if command.client_request_id:
                lock_key = (
                    f"idempotency:chat:{command.user_id}:"
                    f"{command.client_request_id}"
                )
                lock_token = f"processing:{uuid.uuid4()}"
                is_new = bool(
                    await self.redis.set(lock_key, lock_token, nx=True, ex=300)
                )
                set_span_attributes(span, {"chat.idempotency.is_new": is_new})
                if not is_new:
                    value = await self.redis.get(lock_key)
                    set_span_attributes(span, {"chat.idempotency.value": value})

        return ChatIdempotencyState(
            lock_key=lock_key,
            lock_token=lock_token,
            is_new=is_new,
            value=value,
        )

    async def prepare_request(
        self,
        *,
        command: ChatQueryCommand,
        idempotency: ChatIdempotencyState,
        trace_attrs: dict[str, object],
        span_prefix: str,
    ) -> ChatPreparedRequest:
        async with db_concurrency_slot(trace_attrs):
            async with self.uow:
                with trace_span(
                    f"{span_prefix}.create_session_and_messages",
                    trace_attrs,
                ) as span:
                    user = await self.uow.user_repo.get_with_lock(command.user_id)
                    if user and user.used_tokens >= user.max_tokens:
                        await self.release_idempotency(idempotency)
                        raise app_validation_error(
                            "Token 余额不足",
                            code="TOKEN_QUOTA_EXCEEDED",
                            details={
                                "used": user.used_tokens,
                                "max": user.max_tokens,
                            },
                        )

                    session_manager = self._session_manager
                    resolved_kb_id = command.kb_id
                    if command.session_id is None and resolved_kb_id is None:
                        default_kb = (
                            await self.uow.knowledge_repo.get_kb_by_name_for_user(
                                name=DEFAULT_KNOWLEDGE_BASE_NAME,
                                user_id=command.user_id,
                            )
                        )
                        if default_kb is not None:
                            resolved_kb_id = default_kb.id

                    session = await session_manager.ensure_session(
                        user_id=command.user_id,
                        query_text=command.query_text,
                        session_id=command.session_id,
                        kb_id=resolved_kb_id,
                    )
                    effective_kb_id = command.kb_id or session.kb_id
                    await session_manager.create_user_message(
                        session_id=session.id,
                        content=command.query_text,
                        user_id=command.user_id,
                    )
                    assistant_message = (
                        await session_manager.create_assistant_message(
                            session_id=session.id,
                            client_request_id=command.client_request_id,
                            user_id=command.user_id,
                        )
                    )
                set_span_attributes(
                    span,
                    {
                        "chat.session_id": session.id,
                        "chat.assistant_message_id": assistant_message.id,
                    },
                )
                trace_attrs["chat.session_id"] = session.id
                trace_attrs["chat.assistant_message_id"] = assistant_message.id

                with trace_span(f"{span_prefix}.fetch_history", trace_attrs) as span:
                    history_messages = await session_manager.get_session_messages(
                        session_id=session.id,
                        limit=settings.CHAT_MEMORY_FETCH_LIMIT,
                    )
                    context_state = await self.uow.chat_repo.get_context_state(
                        session.id
                    )
                    set_span_attributes(
                        span, {"chat.history.message_count": len(history_messages)}
                    )

        with trace_span(f"{span_prefix}.prepare_worker_payload", trace_attrs) as span:
            conversation_history = history_to_conversation_messages(history_messages)
            set_span_attributes(
                span,
                {
                    "chat.history.message_count": len(conversation_history),
                    "rag.deferred_to_worker": effective_kb_id is not None,
                },
            )

        generation_payload = GenerationPayload(
            session_id=session.id,
            query_text=command.query_text,
            conversation_history=conversation_history,
            kb_id=effective_kb_id,
            context_state=context_state,
            extra_body=command.extra_body,
        )
        return ChatPreparedRequest(
            session=session,
            assistant_message=assistant_message,
            generation_payload=generation_payload,
            lock_key=idempotency.lock_key,
            lock_token=idempotency.lock_token,
            trace_attrs=trace_attrs,
        )

    async def release_idempotency(self, idempotency: ChatIdempotencyState) -> None:
        if idempotency.lock_key is None or idempotency.lock_token is None:
            return
        await safe_release_lock(
            self.redis,
            idempotency.lock_key,
            idempotency.lock_token,
        )
