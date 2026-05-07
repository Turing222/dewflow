"""Non-streaming chat workflow.

职责：编排非流式聊天请求的幂等、会话消息和 Worker 任务投递。
边界：LLM 调用和最终消息持久化由 Worker 拥有；本模块只负责 Web 侧编排和 HTTP 响应。
失败处理：任务投递前失败由 Web 回写；任务投递后最终消息状态由 Worker 拥有。
"""

import logging
import uuid

import redis.asyncio as redis
from langfuse import get_client, observe

from backend.application.chat.history_projection import history_to_conversation_messages
from backend.config.settings import settings
from backend.contracts.interfaces import (
    AbstractTaskDispatcher,
    AbstractUnitOfWork,
)
from backend.core.concurrency import db_concurrency_slot
from backend.core.exceptions import (
    AppException,
    app_service_error,
    app_validation_error,
)
from backend.infra.redis import safe_release_lock
from backend.models.orm.chat import MessageStatus
from backend.models.schemas.chat.api import (
    ChatQueryResponse,
    MessageResponse,
    MessageStatusEnum,
)
from backend.models.schemas.chat.commands import ChatQueryCommand
from backend.models.schemas.chat.payloads import GenerationPayload
from backend.observability.trace_utils import (
    inject_trace_context,
    set_span_attributes,
    trace_span,
)
from backend.services.chat_service import SessionManager
from backend.services.knowledge_service import DEFAULT_KNOWLEDGE_BASE_NAME

logger = logging.getLogger(__name__)


class ChatNonStreamWorkflow:
    """非流式对话编排器 —— Web 侧负责会话管理、RAG 检索、Worker 投递。"""

    def __init__(
        self,
        uow: AbstractUnitOfWork,
        dispatcher: AbstractTaskDispatcher,
        redis_client: redis.Redis,
    ) -> None:
        self.uow = uow
        self.dispatcher = dispatcher
        self.redis = redis_client

    # ── Main handler ──────────────────────────────────────────────

    @observe()
    async def handle_query(
        self,
        command: ChatQueryCommand,
    ) -> ChatQueryResponse:
        user_id = command.user_id
        query_text = command.query_text
        session_id = command.session_id
        kb_id = command.kb_id
        client_request_id = command.client_request_id
        extra_body = command.extra_body
        get_client().update_current_trace(
            user_id=str(user_id),
            session_id=str(session_id) if session_id else None,
            tags=["chat_api", "non-stream"],
        )
        logger.info(
            "Workflow 收到查询: user_id=%s, session_id=%s, query_len=%d",
            user_id,
            session_id,
            len(query_text),
        )

        lock_key: str | None = None
        lock_token: str | None = None
        trace_attrs = {
            "chat.user_id": user_id,
            "chat.session_id": session_id,
            "chat.kb_id": kb_id,
            "chat.client_request_id.present": client_request_id is not None,
            "chat.query.char_count": len(query_text),
            "chat.stream": False,
        }

        # ── 幂等检查 ──────────────────────────────────────────────

        with trace_span("chat.nonstream.idempotency_check", trace_attrs) as span:
            if client_request_id:
                lock_key = f"idempotency:chat:{user_id}:{client_request_id}"
                lock_token = f"processing:{uuid.uuid4()}"
                is_new = await self.redis.set(lock_key, lock_token, nx=True, ex=300)
                set_span_attributes(span, {"chat.idempotency.is_new": bool(is_new)})
                if not is_new:
                    val = await self.redis.get(lock_key)
                    set_span_attributes(span, {"chat.idempotency.value": val})
                    if val is not None and val.startswith("processing:"):
                        raise app_service_error(
                            "正在加速计算中...",
                            code="CHAT_REQUEST_PROCESSING",
                            details={"client_request_id": client_request_id},
                        )
                    async with self.uow:
                        msg = await self.uow.chat_repo.get_message_by_client_request_id(
                            client_request_id,
                            user_id,
                        )
                        if msg and msg.status == MessageStatus.SUCCESS:
                            session = await self.uow.chat_repo.get_session(
                                msg.session_id
                            )
                            if session is None:
                                raise app_service_error(
                                    "会话不存在",
                                    code="CHAT_SESSION_NOT_FOUND",
                                )
                            set_span_attributes(
                                span,
                                {"chat.idempotency.cached_message": True},
                            )
                            return ChatQueryResponse(
                                session_id=session.id,
                                session_title=session.title,
                                answer=MessageResponse.model_validate(msg),
                            )

        # ── 会话与消息创建 ────────────────────────────────────────

        with trace_span(
            "chat.nonstream.create_session_and_messages", trace_attrs
        ) as span:
            async with db_concurrency_slot(trace_attrs):
                async with self.uow:
                    user = await self.uow.user_repo.get_with_lock(user_id)
                    if user and user.used_tokens >= user.max_tokens:
                        if lock_key is not None and lock_token is not None:
                            await safe_release_lock(self.redis, lock_key, lock_token)
                        raise app_validation_error(
                            "Token 余额不足",
                            code="TOKEN_QUOTA_EXCEEDED",
                            details={"used": user.used_tokens, "max": user.max_tokens},
                        )

                    session_manager = SessionManager(self.uow)
                    resolved_kb_id = kb_id
                    if session_id is None and resolved_kb_id is None:
                        default_kb = (
                            await self.uow.knowledge_repo.get_kb_by_name_for_user(
                                name=DEFAULT_KNOWLEDGE_BASE_NAME,
                                user_id=user_id,
                            )
                        )
                        if default_kb is not None:
                            resolved_kb_id = default_kb.id

                    session = await session_manager.ensure_session(
                        user_id=user_id,
                        query_text=query_text,
                        session_id=session_id,
                        kb_id=resolved_kb_id,
                    )
                    effective_kb_id = kb_id or session.kb_id
                    await session_manager.create_user_message(
                        session_id=session.id,
                        content=query_text,
                        user_id=user_id,
                    )
                    assistant_msg = await session_manager.create_assistant_message(
                        session_id=session.id,
                        client_request_id=client_request_id,
                        user_id=user_id,
                    )
            set_span_attributes(
                span,
                {
                    "chat.session_id": session.id,
                    "chat.assistant_message_id": assistant_msg.id,
                },
            )
            trace_attrs["chat.session_id"] = session.id
            trace_attrs["chat.assistant_message_id"] = assistant_msg.id

        # ── 获取历史消息 ──────────────────────────────────────────

        with trace_span("chat.nonstream.fetch_history", trace_attrs) as span:
            async with db_concurrency_slot(trace_attrs):
                async with self.uow:
                    session_manager = SessionManager(self.uow)
                    history_messages = await session_manager.get_session_messages(
                        session_id=session.id,
                        limit=settings.CHAT_MEMORY_FETCH_LIMIT,
                    )
            set_span_attributes(
                span, {"chat.history.message_count": len(history_messages)}
            )

        # ── Worker payload 准备 ───────────────────────────────────

        with trace_span("chat.nonstream.prepare_worker_payload", trace_attrs) as span:
            conversation_history = history_to_conversation_messages(history_messages)
            set_span_attributes(
                span,
                {
                    "chat.history.message_count": len(conversation_history),
                    "rag.deferred_to_worker": effective_kb_id is not None,
                },
            )

        # ── 投递到 Worker ─────────────────────────────────────────

        generation_payload = GenerationPayload(
            session_id=session.id,
            query_text=query_text,
            conversation_history=conversation_history,
            kb_id=effective_kb_id,
            extra_body=extra_body,
        )

        try:
            with trace_span(
                "chat.nonstream.dispatch_task",
                {
                    **trace_attrs,
                    "chat.assistant_message_id": assistant_msg.id,
                },
            ):
                result = await self.dispatcher.enqueue_nonstream(
                    generation_payload.model_dump(mode="json"),
                    inject_trace_context(),
                    str(assistant_msg.id),
                    str(user_id),
                    lock_key,
                )
        except AppException:
            if lock_key is not None and lock_token is not None:
                await safe_release_lock(self.redis, lock_key, lock_token)
            raise
        except Exception as exc:
            if lock_key is not None and lock_token is not None:
                await safe_release_lock(self.redis, lock_key, lock_token)
            raise app_service_error(
                "LLM 服务调用失败，请稍后重试",
                code="LLM_SERVICE_ERROR",
            ) from exc

        if not result or not result.success:
            error_msg = (
                result.error
                if result and result.error
                else "LLM 服务返回失败"
            )
            raise app_service_error(
                error_msg,
                code="LLM_SERVICE_FAILED",
                details={"error": error_msg},
            )

        # Worker 已持久化成功消息并更新幂等锁；Web 直接构造响应。
        answer = MessageResponse(
            id=assistant_msg.id,
            session_id=session.id,
            role="assistant",
            content=result.content,
            status=MessageStatusEnum.SUCCESS,
            latency_ms=result.latency_ms,
            search_context=result.search_context,
            created_at=assistant_msg.created_at,
            updated_at=assistant_msg.updated_at,
        )

        return ChatQueryResponse(
            session_id=session.id,
            session_title=session.title,
            answer=answer,
        )
