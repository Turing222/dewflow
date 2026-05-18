"""Workspace permission service.

职责：读取用户在 workspace 中的角色，并按配置策略判断权限。
边界：本模块不维护角色数据；角色增删改由 WorkspaceService/repository 负责。
风险：缺失 workspace 或角色时的默认行为完全由权限配置控制。
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from backend.config.permissions import get_permission_policy, get_permissions_config
from backend.contracts.interfaces import AbstractUnitOfWork
from backend.core.exceptions import app_forbidden
from backend.models.enums import Permission, WorkspaceRole
from backend.models.orm.user import User
from backend.models.schemas.permission_schema import (
    PermissionDescription,
    PermissionPolicyResponse,
)
from backend.services.base import BaseService


class PermissionService(BaseService[AbstractUnitOfWork]):
    """配置文件驱动的工作区权限判断入口。"""

    def __init__(self, uow: AbstractUnitOfWork) -> None:
        super().__init__(uow)
        self.policy = get_permission_policy()

    async def get_workspace_role(
        self,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> WorkspaceRole | None:
        access_repo = getattr(self.uow, "access_repo", None)
        if access_repo is not None:
            return await access_repo.get_workspace_role(
                user_id=user_id,
                workspace_id=workspace_id,
            )
        raise RuntimeError("PermissionService requires uow.access_repo.")

    async def has_permission(
        self,
        *,
        user: User,
        workspace_id: uuid.UUID | None,
        permission: Permission,
    ) -> bool:
        if user.is_superuser and self.policy.superuser_bypass:
            return True
        if workspace_id is None:
            return self.policy.allows_missing_workspace()

        role = await self.get_workspace_role(
            user_id=user.id,
            workspace_id=workspace_id,
        )
        return self.role_has_permission(role=role, permission=permission)

    async def has_permission_for_user_id(
        self,
        *,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID | None,
        permission: Permission,
    ) -> bool:
        user_repo = getattr(self.uow, "user_repo", None)
        if user_repo is None:
            return False
        user = await user_repo.get(user_id)
        if not user:
            return False
        return await self.has_permission(
            user=user,
            workspace_id=workspace_id,
            permission=permission,
        )

    async def require_permission(
        self,
        *,
        user: User,
        workspace_id: uuid.UUID | None,
        permission: Permission,
    ) -> None:
        if await self.has_permission(
            user=user,
            workspace_id=workspace_id,
            permission=permission,
        ):
            return

        raise app_forbidden(
            "权限不足",
            details={
                "workspace_id": str(workspace_id) if workspace_id else None,
                "permission": permission,
            },
        )

    def role_has_permission(
        self,
        *,
        role: WorkspaceRole | None,
        permission: Permission,
    ) -> bool:
        return self.policy.role_has_permission(role=role, permission=permission)

    @staticmethod
    def default_role_has_permission(
        *,
        role: WorkspaceRole | None,
        permission: Permission,
    ) -> bool:
        return get_permission_policy().role_has_permission(
            role=role,
            permission=permission,
        )

    def get_policy_response(self) -> PermissionPolicyResponse:
        """返回权限策略元数据（用于 API 响应）。"""
        config = get_permissions_config()
        policy = get_permission_policy()

        permissions = [
            PermissionDescription(
                value=Permission(p),
                description=defn.description,
            )
            for p, defn in config.permissions.items()
        ]
        role_permissions = {
            role.value: sorted(
                policy.role_permissions.get(role, frozenset()),
                key=lambda item: item.value,
            )
            for role in WorkspaceRole
        }
        return PermissionPolicyResponse(
            permissions=permissions,
            roles=list(WorkspaceRole),
            role_permissions=role_permissions,
        )

    async def ensure_audit_access(
        self,
        *,
        user: User,
        workspace_id: uuid.UUID | None,
    ) -> None:
        """验证用户是否有审计读取权限，无权限则抛 app_forbidden。"""
        if user.is_superuser and self.policy.superuser_bypass:
            return
        if workspace_id is None:
            raise app_forbidden(
                "权限不足",
                details={"scope": "global", "permission": Permission.AUDIT_READ},
            )
        await self.require_permission(
            user=user,
            workspace_id=workspace_id,
            permission=Permission.AUDIT_READ,
        )

    @property
    def _session(self) -> AsyncSession:
        session = getattr(self.uow, "session", None)
        if session is None:
            raise RuntimeError(
                "PermissionService requires an active SQLAlchemy UnitOfWork session."
            )
        return session
