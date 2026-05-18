"""Permission enum definitions.

职责：集中定义代码中可引用的权限标识。
边界：角色到权限的映射由配置文件和 PermissionPolicy 决定。
"""

from backend.models.enums import Permission

__all__ = ["Permission"]
