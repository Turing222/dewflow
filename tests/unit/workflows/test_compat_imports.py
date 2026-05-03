def test_workflow_compat_imports_point_to_application_modules():
    from backend.application.chat.web_stream_workflow import ChatWorkflow as NewChat
    from backend.application.knowledge.ingestion_workflow import (
        KnowledgeRAGWorkflow as NewIngestion,
    )
    from backend.workflow.chat_workflow import ChatWorkflow as OldChat
    from backend.workflow.knowledge_rag_workflow import (
        KnowledgeRAGWorkflow as OldIngestion,
    )

    assert OldChat is NewChat
    assert OldIngestion is NewIngestion


def test_task_compat_imports_point_to_worker_modules():
    from backend.tasks.llm_tasks import generate_llm_stream_task as old_llm_task
    from backend.worker.tasks.llm_tasks import generate_llm_stream_task as new_llm_task

    assert old_llm_task is new_llm_task

