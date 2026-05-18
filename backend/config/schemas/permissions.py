"""Permissions YAML config schema.

职责：定义 access/permissions.yaml 的 Pydantic schema 及跨字段校验。
边界：本模块不读取文件、不查询角色；只验证配置结构和一致性。
失败处理：权限、角色、通配符冲突在 validate_policy 中集中暴露。
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.models.enums import Permission, WorkspaceRole


class PermissionDefinition(BaseModel):
    """单个权限的文档化定义。"""

    description: str = ""

    model_config = ConfigDict(extra="forbid")


class RoleDefinition(BaseModel):
    """workspace 角色包含的权限列表。"""

    permissions: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class PermissionDefaults(BaseModel):
    """权限策略的默认 fallback 行为。"""

    superuser_bypass: bool = True
    missing_workspace: Literal["allow", "deny"] = "deny"
    missing_role: Literal["allow", "deny"] = "deny"

    model_config = ConfigDict(extra="forbid")


class PermissionsConfig(BaseModel):
    """access/permissions.yaml 的完整 schema。"""

    version: int = 1
    permissions: dict[str, PermissionDefinition]
    roles: dict[str, RoleDefinition]
    defaults: PermissionDefaults = Field(default_factory=PermissionDefaults)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_policy(self) -> "PermissionsConfig":
        known_permissions = {permission.value for permission in Permission}
        configured_permissions = set(self.permissions)
        unknown_permissions = configured_permissions - known_permissions
        if unknown_permissions:
            raise ValueError(
                "Unknown permissions in permissions.yaml: "
                f"{sorted(unknown_permissions)}"
            )

        missing_permissions = known_permissions - configured_permissions
        if missing_permissions:
            raise ValueError(
                "permissions.yaml must document every code permission; missing: "
                f"{sorted(missing_permissions)}"
            )

        known_roles = {role.value for role in WorkspaceRole}
        configured_roles = set(self.roles)
        unknown_roles = configured_roles - known_roles
        if unknown_roles:
            raise ValueError(
                f"Unknown roles in permissions.yaml: {sorted(unknown_roles)}"
            )

        missing_roles = known_roles - configured_roles
        if missing_roles:
            raise ValueError(
                f"permissions.yaml must configure every workspace role; missing: "
                f"{sorted(missing_roles)}"
            )

        for role_name, role_config in self.roles.items():
            permissions = role_config.permissions
            if not permissions:
                raise ValueError(f"Role {role_name!r} must define permissions")
            if "*" in permissions and len(permissions) > 1:
                raise ValueError(
                    f"Role {role_name!r} cannot combine '*' with explicit permissions"
                )
            unknown_role_permissions = set(permissions) - known_permissions - {"*"}
            if unknown_role_permissions:
                raise ValueError(
                    f"Role {role_name!r} references unknown permissions: "
                    f"{sorted(unknown_role_permissions)}"
                )

        return self
