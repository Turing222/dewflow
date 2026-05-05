from fastapi import Depends

from backend.api.deps.services import get_knowledge_service, get_task_service
from backend.api.deps.uow import get_uow
from backend.application.chat.web_nonstream_workflow import ChatNonStreamWorkflow
from backend.application.chat.web_stream_workflow import ChatWorkflow
from backend.application.knowledge.upload_workflow import KnowledgeUploadWorkflow
from backend.contracts.interfaces import (
    AbstractTaskDispatcher,
    AbstractUnitOfWork,
)
from backend.infra.task_dispatcher import TaskDispatcher
from backend.services.knowledge_service import KnowledgeService
from backend.services.task_service import TaskService


def get_dispatcher() -> TaskDispatcher:
    return TaskDispatcher()


def get_chat_workflow(
    uow: AbstractUnitOfWork = Depends(get_uow),
    dispatcher: AbstractTaskDispatcher = Depends(get_dispatcher),
) -> ChatWorkflow:
    return ChatWorkflow(uow, dispatcher)


def get_chat_nonstream_workflow(
    uow: AbstractUnitOfWork = Depends(get_uow),
    dispatcher: AbstractTaskDispatcher = Depends(get_dispatcher),
) -> ChatNonStreamWorkflow:
    return ChatNonStreamWorkflow(uow, dispatcher)


def get_knowledge_upload_workflow(
    knowledge_service: KnowledgeService = Depends(get_knowledge_service),
    task_service: TaskService = Depends(get_task_service),
    dispatcher: AbstractTaskDispatcher = Depends(get_dispatcher),
) -> KnowledgeUploadWorkflow:
    return KnowledgeUploadWorkflow(
        knowledge_service=knowledge_service,
        task_service=task_service,
        dispatcher=dispatcher,
    )
