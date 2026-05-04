def test_chat_workflow_imports_from_application():
    """Chat workflows live under application/chat/."""
    from backend.application.chat.web_nonstream_workflow import ChatNonStreamWorkflow
    from backend.application.chat.web_stream_workflow import ChatWorkflow

    assert ChatWorkflow is not None
    assert ChatNonStreamWorkflow is not None


def test_knowledge_workflow_imports_from_application():
    """Knowledge workflows live under application/knowledge/."""
    from backend.application.knowledge.ingestion_workflow import (
        KnowledgeRAGWorkflow,
    )
    from backend.application.knowledge.upload_workflow import (
        KnowledgeUploadWorkflow,
    )

    assert KnowledgeRAGWorkflow is not None
    assert KnowledgeUploadWorkflow is not None


def test_task_imports_from_worker():
    """Tasks live under worker/tasks/."""
    from backend.worker.tasks.knowledge_tasks import ingest_knowledge_file_task
    from backend.worker.tasks.llm_tasks import generate_llm_stream_task

    assert generate_llm_stream_task is not None
    assert ingest_knowledge_file_task is not None
