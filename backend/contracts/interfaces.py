import uuid
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from types import TracebackType
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.schemas.chat_schema import LLMQueryDTO, LLMResultDTO
from backend.repositories.access_repo import AccessRepository
from backend.repositories.chat_repo import ChatRepository
from backend.repositories.knowledge_repo import KnowledgeRepository
from backend.repositories.task_repo import TaskRepository
from backend.repositories.user_repo import UserRepository


class AbstractUnitOfWork(ABC):
    access_repo: AccessRepository
    user_repo: UserRepository
    chat_repo: ChatRepository
    knowledge_repo: KnowledgeRepository
    task_repo: TaskRepository
    session: AsyncSession

    async def __aenter__(self) -> "AbstractUnitOfWork":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if exc_type is None:
            await self.commit()
        else:
            await self.rollback()

    @abstractmethod
    async def commit(self) -> None: ...

    @abstractmethod
    async def rollback(self) -> None: ...


class AbstractLLMService(ABC):
    """
    LLM 服务抽象接口
    与具体的 LLM 提供商解耦 (OpenAI, Claude, Local LLM...)
    """

    @abstractmethod
    async def stream_response(
        self,
        query: LLMQueryDTO,
    ) -> AsyncGenerator[str, None]:
        """流式返回响应"""
        if False:
            yield ""

    @abstractmethod
    async def generate_response(
        self,
        query: LLMQueryDTO,
    ) -> LLMResultDTO:
        """完整返回响应"""
        ...


class AbstractRAGService(ABC):
    """RAG 检索服务抽象接口"""

    @abstractmethod
    async def retrieve(
        self,
        query_text: str,
        kb_id: uuid.UUID | None,
        top_k: int | None = None,
    ) -> list[dict]:
        """返回检索命中的上下文片段"""
        ...

    @abstractmethod
    async def retrieve_fulltext(
        self,
        query_text: str,
        kb_id: uuid.UUID | None,
        top_k: int | None = None,
    ) -> list[dict]:
        """返回全文检索命中的上下文片段"""
        ...

    @abstractmethod
    async def retrieve_hybrid(
        self,
        query_text: str,
        kb_id: uuid.UUID | None,
        top_k: int | None = None,
    ) -> list[dict]:
        """返回混合检索命中的上下文片段"""
        ...

    @abstractmethod
    async def retrieve_with_rerank(
        self,
        query_text: str,
        kb_id: uuid.UUID | None,
        top_k: int | None = None,
        candidate_count: int | None = None,
    ) -> list[dict]:
        """返回经过可选 LLM 重排序的上下文片段"""
        ...


class AbstractRAGEmbedder(ABC):
    """RAG 向量化器抽象接口"""

    @abstractmethod
    def encode_query(self, text: str) -> list[float]:
        """将查询文本编码为向量"""
        ...

    def encode_document(self, text: str) -> list[float]:
        """将文档片段编码为向量；默认复用查询编码。"""
        return self.encode_query(text)

    def encode_documents(self, texts: list[str]) -> list[list[float]]:
        """将文档片段批量编码为向量；默认逐条编码。"""
        return [self.encode_document(text) for text in texts]


class AbstractTaskDispatcher(ABC):
    """Web → Worker 任务投递抽象。

    所有 TaskIQ .kiq() 调用收敛到该接口的实现端，
    Web workflow 只依赖此 Protocol，不直接 import worker.tasks.*。
    """

    @abstractmethod
    async def enqueue_stream(
        self,
        generation_payload: dict[str, Any],
        channel: str,
        trace_context: dict[str, str] | None = None,
        assistant_message_id: str | None = None,
        user_id: str | None = None,
        idempotency_lock_key: str | None = None,
    ) -> None:
        """投递流式 LLM 生成任务到 TaskIQ worker。"""
        ...

    @abstractmethod
    async def enqueue_nonstream(
        self,
        generation_payload: dict[str, Any],
        trace_context: dict[str, str] | None = None,
        assistant_message_id: str | None = None,
        user_id: str | None = None,
        idempotency_lock_key: str | None = None,
    ) -> dict[str, Any]:
        """投递非流式 LLM 生成任务并等待结果返回。"""
        ...

    @abstractmethod
    async def enqueue_ingestion(
        self,
        file_id: str,
        task_id: str | None = None,
        trace_context: dict[str, str] | None = None,
    ) -> None:
        """投递知识库文件入库任务到 TaskIQ worker。"""
        ...
