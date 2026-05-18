"""Audit event persistence repository.

职责：封装审计事件查询、过滤、分页和计数。
边界：本模块不做权限判断；调用方必须先完成审计读取授权。
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.orm.access import AuditEvent
from backend.models.schemas.audit_schema import AuditEventFilters


class AuditRepository:
    """审计事件查询与写入仓储。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, event: AuditEvent) -> None:
        self.session.add(event)
        await self.session.flush()

    async def count_events(self, filters: AuditEventFilters) -> int:
        stmt = self._apply_filters(
            select(func.count()).select_from(AuditEvent),
            filters=filters,
        )
        return await self.session.scalar(stmt) or 0

    async def list_events(
        self,
        *,
        filters: AuditEventFilters,
        skip: int,
        limit: int,
    ) -> Sequence[AuditEvent]:
        stmt = self._apply_filters(select(AuditEvent), filters=filters)
        stmt = stmt.order_by(AuditEvent.created_at.desc()).offset(skip).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    @staticmethod
    def _apply_filters(
        stmt: Select,
        *,
        filters: AuditEventFilters,
    ) -> Select:
        if filters.action:
            stmt = stmt.where(AuditEvent.action == filters.action)
        if filters.outcome:
            stmt = stmt.where(AuditEvent.outcome == filters.outcome)
        if filters.request_id:
            stmt = stmt.where(AuditEvent.request_id == filters.request_id)
        if filters.actor_user_id:
            stmt = stmt.where(AuditEvent.actor_user_id == filters.actor_user_id)
        if filters.workspace_id:
            stmt = stmt.where(AuditEvent.workspace_id == filters.workspace_id)
        return stmt
