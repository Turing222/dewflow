import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from backend.api.dependencies import (
    get_audit_service,
    get_current_active_user,
    get_workspace_service,
)
from backend.core.constants import DEFAULT_PAGE_LIMIT, MAX_PAGE_LIMIT
from backend.models.enums import WorkspaceRole
from backend.models.orm.access import Workspace
from backend.models.orm.user import User
from backend.models.schemas.workspace_schema import (
    WorkspaceCreate,
    WorkspaceListResponse,
    WorkspaceMemberCreate,
    WorkspaceMemberListResponse,
    WorkspaceMemberResponse,
    WorkspaceMemberUpdate,
    WorkspaceResponse,
    WorkspaceUpdate,
)
from backend.services.audit_service import AuditAction, AuditService, capture_audit
from backend.services.workspace_service import WorkspaceService

router = APIRouter()

CurrentUserDep = Annotated[User, Depends(get_current_active_user)]
WorkspaceServiceDep = Annotated[WorkspaceService, Depends(get_workspace_service)]
AuditServiceDep = Annotated[AuditService, Depends(get_audit_service)]


def _workspace_response(
    workspace: Workspace,
    role: WorkspaceRole | None,
) -> WorkspaceResponse:
    return WorkspaceResponse.model_validate(
        {
            "id": workspace.id,
            "name": workspace.name,
            "slug": workspace.slug,
            "owner_id": workspace.owner_id,
            "current_user_role": role,
            "created_at": workspace.created_at,
            "updated_at": workspace.updated_at,
        }
    )


def _member_response(user_role, user: User) -> WorkspaceMemberResponse:
    return WorkspaceMemberResponse.model_validate(
        {
            "id": user_role.id,
            "user_id": user_role.user_id,
            "workspace_id": user_role.workspace_id,
            "username": user.username,
            "email": user.email,
            "role": WorkspaceRole(user_role.role),
            "created_at": user_role.created_at,
            "updated_at": user_role.updated_at,
        }
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
)
async def create_workspace(
    workspace_in: WorkspaceCreate,
    current_user: CurrentUserDep,
    service: WorkspaceServiceDep,
    audit_service: AuditServiceDep,
) -> WorkspaceResponse:
    async with (
        capture_audit(
            audit_service,
            action=AuditAction.WORKSPACE_CREATE,
            actor_user_id=current_user.id,
            resource_type="workspace",
            metadata={"slug": workspace_in.slug},
        ) as audit,
        service.write(),
    ):
        workspace, role = await service.create_workspace(
            current_user=current_user,
            workspace_in=workspace_in,
        )
        audit.set_resource(resource_id=workspace.id)
        return _workspace_response(workspace, role)


@router.get("")
async def list_workspaces(
    current_user: CurrentUserDep,
    service: WorkspaceServiceDep,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)] = DEFAULT_PAGE_LIMIT,
) -> WorkspaceListResponse:
    async with service.read():
        items, total = await service.list_user_workspaces(
            current_user=current_user,
            skip=skip,
            limit=limit,
        )
        return WorkspaceListResponse(
            items=[_workspace_response(workspace, role) for workspace, role in items],
            total=total,
            skip=skip,
            limit=limit,
        )


@router.get("/{workspace_id}")
async def get_workspace(
    workspace_id: uuid.UUID,
    current_user: CurrentUserDep,
    service: WorkspaceServiceDep,
) -> WorkspaceResponse:
    async with service.read():
        workspace, role = await service.get_workspace(
            current_user=current_user,
            workspace_id=workspace_id,
        )
        return _workspace_response(workspace, role)


@router.patch("/{workspace_id}")
async def update_workspace(
    workspace_id: uuid.UUID,
    workspace_in: WorkspaceUpdate,
    current_user: CurrentUserDep,
    service: WorkspaceServiceDep,
    audit_service: AuditServiceDep,
) -> WorkspaceResponse:
    async with (
        capture_audit(
            audit_service,
            action=AuditAction.WORKSPACE_UPDATE,
            actor_user_id=current_user.id,
            workspace_id=workspace_id,
            resource_type="workspace",
            resource_id=workspace_id,
            metadata={"updated_fields": list(workspace_in.model_fields_set)},
        ),
        service.write(),
    ):
        workspace, role = await service.update_workspace(
            current_user=current_user,
            workspace_id=workspace_id,
            workspace_in=workspace_in,
        )
        return _workspace_response(workspace, role)


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace(
    workspace_id: uuid.UUID,
    current_user: CurrentUserDep,
    service: WorkspaceServiceDep,
    audit_service: AuditServiceDep,
) -> Response:
    async with (
        capture_audit(
            audit_service,
            action=AuditAction.WORKSPACE_DELETE,
            actor_user_id=current_user.id,
            workspace_id=workspace_id,
            resource_type="workspace",
            resource_id=workspace_id,
        ),
        service.write(),
    ):
        await service.delete_workspace(
            current_user=current_user,
            workspace_id=workspace_id,
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{workspace_id}/members")
async def list_workspace_members(
    workspace_id: uuid.UUID,
    current_user: CurrentUserDep,
    service: WorkspaceServiceDep,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)] = DEFAULT_PAGE_LIMIT,
) -> WorkspaceMemberListResponse:
    async with service.read():
        items, total = await service.list_workspace_members(
            current_user=current_user,
            workspace_id=workspace_id,
            skip=skip,
            limit=limit,
        )
        return WorkspaceMemberListResponse(
            items=[_member_response(user_role, user) for user_role, user in items],
            total=total,
            skip=skip,
            limit=limit,
        )


@router.post(
    "/{workspace_id}/members",
    status_code=status.HTTP_201_CREATED,
)
async def add_workspace_member(
    workspace_id: uuid.UUID,
    member_in: WorkspaceMemberCreate,
    current_user: CurrentUserDep,
    service: WorkspaceServiceDep,
    audit_service: AuditServiceDep,
) -> WorkspaceMemberResponse:
    async with (
        capture_audit(
            audit_service,
            action=AuditAction.WORKSPACE_MEMBER_ADD,
            actor_user_id=current_user.id,
            workspace_id=workspace_id,
            resource_type="workspace_member",
            resource_id=member_in.user_id,
            metadata={"role": member_in.role},
        ),
        service.write(),
    ):
        user_role, user = await service.add_workspace_member(
            current_user=current_user,
            workspace_id=workspace_id,
            member_in=member_in,
        )
        return _member_response(user_role, user)


@router.patch(
    "/{workspace_id}/members/{user_id}",
)
async def update_workspace_member(
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    member_in: WorkspaceMemberUpdate,
    current_user: CurrentUserDep,
    service: WorkspaceServiceDep,
    audit_service: AuditServiceDep,
) -> WorkspaceMemberResponse:
    async with (
        capture_audit(
            audit_service,
            action=AuditAction.WORKSPACE_MEMBER_UPDATE,
            actor_user_id=current_user.id,
            workspace_id=workspace_id,
            resource_type="workspace_member",
            resource_id=user_id,
            metadata={"role": member_in.role},
        ),
        service.write(),
    ):
        user_role, user = await service.update_workspace_member(
            current_user=current_user,
            workspace_id=workspace_id,
            user_id=user_id,
            member_in=member_in,
        )
        return _member_response(user_role, user)


@router.delete(
    "/{workspace_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_workspace_member(
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: CurrentUserDep,
    service: WorkspaceServiceDep,
    audit_service: AuditServiceDep,
) -> Response:
    async with (
        capture_audit(
            audit_service,
            action=AuditAction.WORKSPACE_MEMBER_REMOVE,
            actor_user_id=current_user.id,
            workspace_id=workspace_id,
            resource_type="workspace_member",
            resource_id=user_id,
        ),
        service.write(),
    ):
        await service.remove_workspace_member(
            current_user=current_user,
            workspace_id=workspace_id,
            user_id=user_id,
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
