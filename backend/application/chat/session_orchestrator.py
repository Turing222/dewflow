"""Shared web chat request preparation.

职责：复用 Web 流式和非流式聊天的幂等、会话、消息和 payload 准备流程。
边界：本模块不序列化 HTTP/SSE 响应，也不消费 Worker 流式结果。
失败处理：准备阶段失败由调用方按 stream/non-stream 协议转换响应。
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

import redis.asyncio as redis

from backend.application.chat.history_projection import history_to_conversation_messages
from backend.utils.token_estimation import count_messages_tokens, count_tokens
from backend.config.credit_settings import credit_settings
from backend.config.llm import get_llm_model_config
from backend.config.settings import settings
from backend.contracts.interfaces import AbstractUnitOfWork
from backend.core.concurrency import db_concurrency_slot
from backend.core.exceptions import AppException, app_bad_request
from backend.infra.redis import safe_release_lock
from backend.models.schemas.chat.commands import ChatQueryCommand
from backend.models.schemas.chat.payloads import GenerationPayload
from backend.observability.trace_utils import set_span_attributes, trace_span
from backend.services.chat_service import SessionManager
from backend.services.credit_service import CreditService
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
                    f"idempotency:chat:{command.user_id}:{command.client_request_id}"
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
        try:
            return await self._prepare_request_inner(
                command=command,
                idempotency=idempotency,
                trace_attrs=trace_attrs,
                span_prefix=span_prefix,
            )
        except AppException:
            await self.release_idempotency(idempotency)
            raise

    async def _prepare_request_inner(
        self,
        *,
        command: ChatQueryCommand,
        idempotency: ChatIdempotencyState,
        trace_attrs: dict[str, object],
        span_prefix: str,
    ) -> ChatPreparedRequest:
        async with db_concurrency_slot(trace_attrs):  # noqa: SIM117
            async with self.uow:
                with trace_span(
                    f"{span_prefix}.create_session_and_messages",
                    trace_attrs,
                ) as span:
                    session_manager = self._session_manager
                    resolved_kb_id = command.kb_id

                    session = await session_manager.ensure_session(
                        user_id=command.user_id,
                        query_text=command.query_text,
                        session_id=command.session_id,
                        kb_id=resolved_kb_id,
                    )
                    # 已有会话：session.kb_id 不可覆盖；新会话：使用经权限校验的 resolved_kb_id。
                    if command.session_id is not None:
                        if command.kb_id is not None and command.kb_id != session.kb_id:
                            raise app_bad_request(
                                "请求的知识库与会话绑定的知识库不一致",
                                code="KB_ID_MISMATCH",
                                details={
                                    "request_kb_id": str(command.kb_id),
                                    "session_kb_id": str(session.kb_id),
                                },
                            )
                        effective_kb_id = session.kb_id
                    else:
                        effective_kb_id = resolved_kb_id or session.kb_id
                    await session_manager.create_user_message(
                        session_id=session.id,
                        content=command.query_text,
                        user_id=command.user_id,
                    )
                    assistant_message = await session_manager.create_assistant_message(
                        session_id=session.id,
                        client_request_id=command.client_request_id,
                        user_id=command.user_id,
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

                with trace_span(f"{span_prefix}.credit_precheck", trace_attrs) as span:
                    conversation_history = history_to_conversation_messages(
                        history_messages
                    )
                    model_name = _resolve_billing_model_name()
                    estimated_cost = _estimate_credit_cost(
                        query_text=command.query_text,
                        conversation_history=conversation_history,
                        model_name=model_name,
                    )
                    set_span_attributes(
                        span,
                        {
                            "credit.estimated_cost": estimated_cost,
                            "credit.model_name": model_name,
                        },
                    )
                    await CreditService(self.uow).ensure_sufficient_balance(
                        command.user_id, estimated_cost=estimated_cost
                    )

        with trace_span(f"{span_prefix}.prepare_worker_payload", trace_attrs) as span:
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


def _resolve_billing_model_name() -> str:
    """Resolve the model name used for credit billing (first candidate)."""
    try:
        config = get_llm_model_config()
        profiles = config.resolve_route(settings.LLM_PROVIDER)
        return profiles[0].model
    except Exception:
        return "default"


def _estimate_credit_cost(
    *,
    query_text: str,
    conversation_history: list[dict],
    model_name: str,
) -> int:
    """Estimate credit cost based on input tokens + estimated output tokens."""
    model_for_counting = "gpt-4"
    input_tokens = count_tokens(query_text, model_for_counting)
    if conversation_history:
        input_tokens += count_messages_tokens(
            conversation_history, model_for_counting
        )

    output_tokens = credit_settings.CREDIT_ESTIMATED_OUTPUT_TOKENS
    rates = credit_settings.CREDIT_MODEL_RATES.get(model_name) or credit_settings.CREDIT_MODEL_RATES.get("default", {})
    input_rate = rates.get("input", 1.0)
    output_rate = rates.get("output", 1.0)

    raw_cost = (input_tokens * input_rate + output_tokens * output_rate) / 1000.0
    return max(math.ceil(raw_cost), credit_settings.CREDIT_MINIMUM_ESTIMATED_COST)
