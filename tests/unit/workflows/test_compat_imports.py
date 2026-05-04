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


def test_dispatcher_imports_from_infra():
    """Task dispatcher lives under infra/."""
    from backend.infra.task_dispatcher import TaskDispatcher

    assert TaskDispatcher is not None


def test_web_workflows_do_not_import_worker_or_ai_runtime():
    """Web-facing modules must not import worker tasks or AI runtime directly."""
    import ast
    import importlib

    web_modules = [
        "backend.application.chat.web_stream_workflow",
        "backend.application.chat.web_nonstream_workflow",
        "backend.application.knowledge.upload_workflow",
        "backend.api.deps.workflows",
        "backend.api.dependencies",
    ]
    forbidden_prefixes = (
        "backend.worker.tasks",
        "backend.ai",
        "backend.api.deps.ai",
        "backend.application.chat.worker_generation_workflow",
        "backend.application.knowledge.ingestion_workflow",
    )

    for mod_name in web_modules:
        mod = importlib.import_module(mod_name)
        source = ast.parse(open(mod.__file__).read())
        for node in ast.walk(source):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    full = f"{module}.{alias.name}" if module else alias.name
                    assert not full.startswith(forbidden_prefixes), (
                        f"{mod_name} imports {full}"
                    )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith(forbidden_prefixes), (
                        f"{mod_name} imports {alias.name}"
                    )
