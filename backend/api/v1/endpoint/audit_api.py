import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from backend.api.dependencies import (
    get_current_active_user,
    get_permission_service,
    get_uow,
)
from backend.contracts.interfaces import AbstractUnitOfWork
from backend.core.constants import DEFAULT_PAGE_LIMIT, MAX_AUDIT_PAGE_LIMIT
from backend.core.exceptions import app_forbidden
from backend.models.orm.access import AuditOutcome
from backend.models.orm.user import User
from backend.models.schemas.audit_schema import (
    AuditEventListResponse,
    AuditEventResponse,
)
from backend.repositories.audit_repo import AuditEventFilters
from backend.services.permission_service import Permission, PermissionService

router = APIRouter()

CurrentUserDep = Annotated[User, Depends(get_current_active_user)]
UOWDep = Annotated[AbstractUnitOfWork, Depends(get_uow)]
PermissionServiceDep = Annotated[PermissionService, Depends(get_permission_service)]


async def _ensure_audit_access(
    *,
    current_user: User,
    workspace_id: uuid.UUID | None,
    permission_service: PermissionService,
) -> None:
    if current_user.is_superuser and permission_service.policy.superuser_bypass:
        return
    if workspace_id is None:
        raise app_forbidden(
            "权限不足",
            details={"scope": "global", "permission": Permission.AUDIT_READ},
        )

    await permission_service.require_permission(
        user=current_user,
        workspace_id=workspace_id,
        permission=Permission.AUDIT_READ,
    )


@router.get("/events", response_model=AuditEventListResponse)
async def list_audit_events(
    current_user: CurrentUserDep,
    uow: UOWDep,
    permission_service: PermissionServiceDep,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_AUDIT_PAGE_LIMIT)] = DEFAULT_PAGE_LIMIT,
    action: str | None = Query(None, max_length=80),
    outcome: AuditOutcome | None = None,
    request_id: str | None = Query(None, max_length=64),
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
    async with uow.read_context():
        await _ensure_audit_access(
            current_user=current_user,
            workspace_id=workspace_id,
            permission_service=permission_service,
        )
        total = await uow.audit_repo.count_events(filters)
        events = await uow.audit_repo.list_events(
            filters=filters,
            skip=skip,
            limit=limit,
        )

    return AuditEventListResponse(
        items=[AuditEventResponse.model_validate(event) for event in events],
        total=total,
        skip=skip,
        limit=limit,
    )
