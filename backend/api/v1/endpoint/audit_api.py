import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from backend.api.dependencies import (
    get_audit_service,
    get_current_active_user,
    get_permission_service,
)
from backend.core.constants import DEFAULT_PAGE_LIMIT, MAX_AUDIT_PAGE_LIMIT
from backend.models.enums import AuditOutcome
from backend.models.orm.user import User
from backend.models.schemas.audit_schema import (
    AuditEventFilters,
    AuditEventListResponse,
    AuditEventResponse,
)
from backend.services.audit_service import AuditService
from backend.services.permission_service import PermissionService

router = APIRouter()

CurrentUserDep = Annotated[User, Depends(get_current_active_user)]
AuditServiceDep = Annotated[AuditService, Depends(get_audit_service)]
PermissionServiceDep = Annotated[PermissionService, Depends(get_permission_service)]


@router.get("/events")
async def list_audit_events(
    current_user: CurrentUserDep,
    audit_service: AuditServiceDep,
    permission_service: PermissionServiceDep,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_AUDIT_PAGE_LIMIT)] = DEFAULT_PAGE_LIMIT,
    action: Annotated[str | None, Query(max_length=80)] = None,
    outcome: AuditOutcome | None = None,
    request_id: Annotated[str | None, Query(max_length=64)] = None,
    actor_user_id: uuid.UUID | None = None,
    workspace_id: uuid.UUID | None = None,
) -> AuditEventListResponse:
    filters = AuditEventFilters(
        action=action,
        outcome=outcome,
        request_id=request_id,
        actor_user_id=actor_user_id,
        workspace_id=workspace_id,
    )
    async with audit_service.read():
        await permission_service.ensure_audit_access(
            user=current_user,
            workspace_id=workspace_id,
        )
        total, events = await audit_service.list_events(
            filters=filters,
            skip=skip,
            limit=limit,
        )
    return AuditEventListResponse(
        items=[AuditEventResponse.model_validate(e) for e in events],
        total=total,
        skip=skip,
        limit=limit,
    )
