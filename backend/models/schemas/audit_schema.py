"""Audit response schemas.

职责：定义审计事件查询接口的响应结构。
边界：本模块不记录审计事件，也不做权限过滤。
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from backend.models.orm.access import AuditOutcome


class AuditEventResponse(BaseModel):
    id: uuid.UUID
    actor_user_id: uuid.UUID | None = None
    workspace_id: uuid.UUID | None = None
    action: str
    resource_type: str | None = None
    resource_id: uuid.UUID | None = None
    outcome: AuditOutcome
    ip: str | None = None
    user_agent: str | None = None
    request_id: str | None = None
    event_metadata: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AuditEventListResponse(BaseModel):
    items: list[AuditEventResponse]
    total: int = Field(..., ge=0)
    skip: int = Field(..., ge=0)
    limit: int = Field(..., ge=1)
