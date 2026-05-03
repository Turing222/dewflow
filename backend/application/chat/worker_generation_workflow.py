"""Worker-side LLM generation workflow.

职责：在 TaskIQ worker 中调用 LLM、发布流式 chunk，并拥有最终消息状态落库。
边界：Web 负责创建会话和消息占位；本 workflow 不做认证/鉴权/HTTP 响应。
失败处理：业务和系统异常都会尽力回写助手消息失败状态，并通过 Redis 通知等待方。
"""

import logging
import time
import uuid

from backend.ai.core.token_counter import count_tokens
from backend.config.llm import get_llm_model_config
from backend.contracts.interfaces import AbstractLLMService, AbstractUnitOfWork
from backend.core.exceptions import AppException
from backend.infra.redis import redis_client
from backend.models.schemas.chat_schema import LLMQueryDTO
from backend.observability.trace_utils import set_span_attributes, trace_span
from backend.services.chat_service import ChatMessageUpdater

logger = logging.getLogger(__name__)


class LLMGenerationWorkerWorkflow:
    """Worker-side streaming generation and persistence workflow."""

    def __init__(
        self,
        *,
        uow: AbstractUnitOfWork,
        llm_service: AbstractLLMService,
    ) -> None:
        self.uow = uow
        self.llm_service = llm_service

    async def generate_stream(
        self,
        *,
        llm_query: LLMQueryDTO,
        channel: str,
        assistant_message_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        tokens_input: int | None = None,
        search_context: dict | None = None,
        idempotency_lock_key: str | None = None,
    ) -> None:
        """Generate a streaming answer, publish chunks, and persist final state."""
        redis_connection = await redis_client.init()
        accumulated_content: list[str] = []
        start_time = time.time()

        try:
            with trace_span(
                "taskiq.llm_stream.generate_and_publish",
                {
                    "redis.channel": channel,
                    "chat.session_id": llm_query.session_id,
                    "chat.assistant_message_id": assistant_message_id,
                    "llm.provider": getattr(self.llm_service, "provider_name", "unknown"),
                    "gen_ai.request.model": getattr(
                        self.llm_service, "model_name", "unknown"
                    ),
                },
            ) as span:
                async for chunk in self.llm_service.stream_response(llm_query):
                    accumulated_content.append(chunk)
                    await redis_connection.publish(channel, chunk)

                full_content = "".join(accumulated_content)
                tokens_output = self._count_output_tokens(full_content)
                await self._persist_success(
                    assistant_message_id=assistant_message_id,
                    user_id=user_id,
                    content=full_content,
                    tokens_input=tokens_input,
                    tokens_output=tokens_output,
                    search_context=search_context,
                    start_time=start_time,
                )
                if idempotency_lock_key is not None and assistant_message_id is not None:
                    await redis_connection.set(
                        idempotency_lock_key,
                        str(assistant_message_id),
                        ex=3600,
                    )

                set_span_attributes(
                    span,
                    {
                        "llm.response.chunk_count": len(accumulated_content),
                        "llm.response.char_count": len(full_content),
                        "chat.tokens_input": tokens_input,
                        "chat.tokens_output": tokens_output,
                    },
                )
            logger.info("TaskIQ Worker 成功结束流式处理: %s", channel)
        except AppException as exc:
            logger.warning("TaskIQ 调用 LLM 业务异常: %s", exc)
            await self._persist_failure(
                assistant_message_id=assistant_message_id,
                error_content=str(exc),
                idempotency_lock_key=idempotency_lock_key,
            )
            await redis_connection.publish(channel, f"[ERROR]{exc}")
        except Exception:
            logger.exception("TaskIQ 调用 LLM 系统异常")
            await self._persist_failure(
                assistant_message_id=assistant_message_id,
                error_content="服务暂时不可用，请稍后重试",
                idempotency_lock_key=idempotency_lock_key,
            )
            await redis_connection.publish(channel, "[ERROR]服务暂时不可用，请稍后重试")
        finally:
            await redis_connection.publish(channel, "[DONE]")

    def _count_output_tokens(self, content: str) -> int:
        model_name = getattr(
            self.llm_service,
            "model_name",
            get_llm_model_config().resolve_profile().model,
        )
        return count_tokens(content, model_name)

    async def _persist_success(
        self,
        *,
        assistant_message_id: uuid.UUID | None,
        user_id: uuid.UUID | None,
        content: str,
        tokens_input: int | None,
        tokens_output: int,
        search_context: dict | None,
        start_time: float,
    ) -> None:
        if assistant_message_id is None:
            return

        async with self.uow:
            updater = ChatMessageUpdater(self.uow)
            await updater.update_as_success(
                message_id=assistant_message_id,
                content=content,
                start_time=start_time,
                tokens_input=tokens_input,
                tokens_output=tokens_output,
                search_context=search_context,
            )
            if user_id is None or tokens_input is None:
                return

            total_tokens = tokens_input + tokens_output
            ok = await self.uow.user_repo.increment_used_tokens_guarded(
                user_id,
                total_tokens,
            )
            if not ok:
                logger.warning(
                    "Token 累加后超出上限，本次消耗未记录: user_id=%s, delta=%d",
                    user_id,
                    total_tokens,
                )

    async def _persist_failure(
        self,
        *,
        assistant_message_id: uuid.UUID | None,
        error_content: str,
        idempotency_lock_key: str | None,
    ) -> None:
        if idempotency_lock_key is not None:
            try:
                redis_connection = await redis_client.init()
                await redis_connection.delete(idempotency_lock_key)
            except Exception:
                logger.debug(
                    "Worker 清理幂等锁失败: key=%s",
                    idempotency_lock_key,
                    exc_info=True,
                )

        if assistant_message_id is None:
            return

        try:
            async with self.uow:
                updater = ChatMessageUpdater(self.uow)
                await updater.update_as_failed(
                    message_id=assistant_message_id,
                    error_content=error_content,
                )
        except Exception:
            logger.exception(
                "Worker 回写助手消息失败状态异常: message_id=%s",
                assistant_message_id,
            )
