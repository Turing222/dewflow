"""Knowledge ingestion recovery service.

职责：扫描长期停留在入库中间态的知识文件和任务，并标记为失败。
边界：本模块不重新投递任务、不删除文件或索引；只做可观测的状态恢复。
风险：超时时间过短会误伤慢文件，调用方应使用保守阈值。
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from backend.config.ai_settings import ai_settings
from backend.contracts.interfaces import AbstractUnitOfWork
from backend.services.base import BaseService

STALE_INGESTION_ERROR = "知识文件入库超时，已自动标记失败"


@dataclass(frozen=True)
class KnowledgeIngestionRecoveryResult:
    """知识文件入库恢复结果。"""

    failed_file_count: int
    failed_task_count: int


class KnowledgeIngestionRecoveryService(BaseService[AbstractUnitOfWork]):
    """恢复卡在入库中间态的知识文件和任务。"""

    def __init__(
        self,
        uow: AbstractUnitOfWork,
        *,
        stale_timeout_seconds: int | None = None,
    ) -> None:
        super().__init__(uow)
        self.stale_timeout_seconds = (
            stale_timeout_seconds
            if stale_timeout_seconds is not None
            else ai_settings.KNOWLEDGE_INGEST_STALE_TIMEOUT_SECONDS
        )

    async def recover_stale_ingestions(
        self,
        *,
        now: datetime | None = None,
    ) -> KnowledgeIngestionRecoveryResult:
        current_time = now or datetime.now(UTC)
        older_than = current_time - timedelta(seconds=self.stale_timeout_seconds)
        failed_file_count = (
            await self.uow.knowledge_repo.mark_stale_ingestion_files_failed(
                older_than=older_than,
            )
        )
        failed_task_count = (
            await self.uow.task_repo.mark_stale_kb_ingestion_tasks_failed(
                older_than=older_than,
                error_log=STALE_INGESTION_ERROR,
            )
        )
        return KnowledgeIngestionRecoveryResult(
            failed_file_count=failed_file_count,
            failed_task_count=failed_task_count,
        )
