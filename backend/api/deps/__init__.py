from importlib import import_module

from backend.api.deps.audit import get_audit_service
from backend.api.deps.auth import (
    get_current_active_user,
    get_current_superuser,
    get_current_user,
    get_login_data,
    reusable_oauth2,
)
from backend.api.deps.permissions import get_permission_service
from backend.api.deps.services import (
    get_knowledge_service,
    get_object_storage,
    get_task_service,
    get_user_import_service,
    get_user_service,
)
from backend.api.deps.uow import get_uow
from backend.api.deps.workflows import (
    get_chat_nonstream_workflow,
    get_chat_workflow,
    get_knowledge_upload_workflow,
)

_AI_EXPORTS = {
    "get_chunking_service",
    "get_llm_service",
    "get_rag_embedder",
    "get_rag_service",
    "get_vector_index_service",
    "get_knowledge_rag_workflow",
}

__all__ = [
    "reusable_oauth2",
    "get_uow",
    "get_current_user",
    "get_current_active_user",
    "get_current_superuser",
    "get_login_data",
    "get_audit_service",
    "get_knowledge_service",
    "get_object_storage",
    "get_permission_service",
    "get_task_service",
    "get_user_service",
    "get_user_import_service",
    "get_chat_nonstream_workflow",
    "get_chat_workflow",
    "get_knowledge_upload_workflow",
]


# 向后兼容的延迟导入：避免 Web 侧直接 import backend.api.deps.ai。
# 新代码应直接从 backend.api.deps.ai 导入 AI 相关依赖。
def __getattr__(name: str):
    if name in _AI_EXPORTS:
        return getattr(import_module("backend.api.deps.ai"), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
