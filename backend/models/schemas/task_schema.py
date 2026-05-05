"""Task response schemas.

职责：定义异步任务状态查询的响应结构。
边界：本模块不创建、调度或执行任务。
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    action_type: str
    status: str
    progress: int
    payload: dict
    error_log: str | None = None
    created_at: datetime
    updated_at: datetime
