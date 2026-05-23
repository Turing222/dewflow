"""Credits background tasks.

职责：定义 Credits 相关的 TaskIQ 定时与后台任务。
边界：仅负责任务的 TaskIQ broker 接入与依赖装配，核心业务逻辑委派给 CreditService。
"""

import logging

from backend.infra.task_broker import broker
from backend.services.credit_service import CreditService
from backend.services.unit_of_work import SQLAlchemyUnitOfWork
from backend.worker.dependencies import get_worker_session_factory

logger = logging.getLogger(__name__)


@broker.task(task_name="expire_credits")
async def expire_credits_task() -> int:
    """TaskIQ 定时后台任务：扫描并扣减已过期的赠送额度。

    由外部 Scheduler/Cron 调度器每日调用。
    """
    logger.info("TaskIQ expire_credits_task started")
    uow = SQLAlchemyUnitOfWork(get_worker_session_factory())
    service = CreditService(uow)

    # 外部事务：expire_credits 内部对每个账户使用 select FOR UPDATE 在独立的子事务/行级锁中操作，
    # 这里的 write context 确保 session 被正确提交与释放。
    async with service.write():
        expired_count = await service.expire_credits()

    logger.info(
        "TaskIQ expire_credits_task completed. Expired %d accounts.", expired_count
    )
    return expired_count
