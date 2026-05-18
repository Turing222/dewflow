"""Permission policy response schemas.

职责：定义权限和角色策略的只读响应结构。
边界：本模块不计算权限继承，也不执行鉴权判断。
"""

from pydantic import BaseModel

from backend.models.enums import Permission, WorkspaceRole


class PermissionDescription(BaseModel):
    value: Permission
    description: str = ""


class RolePolicyResponse(BaseModel):
    value: WorkspaceRole
    permissions: list[Permission]


class PermissionPolicyResponse(BaseModel):
    permissions: list[PermissionDescription]
    roles: list[WorkspaceRole]
    role_permissions: dict[str, list[Permission]]
