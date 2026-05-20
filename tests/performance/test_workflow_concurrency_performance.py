import asyncio
import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.application.chat.web_stream_workflow import ChatWorkflow
from backend.models.schemas.chat.commands import ChatQueryCommand

pytestmark = [pytest.mark.asyncio, pytest.mark.performance]


async def test_workflow_concurrency():
    with (
        patch(
            "backend.application.chat.web_stream_workflow.settings.LLM_MAX_CONCURRENCY",
            2,
        ),
        patch(
            "backend.application.chat.web_stream_workflow.settings.DB_MAX_CONCURRENCY",
            2,
        ),
    ):
        ChatWorkflow._llm_semaphore = asyncio.Semaphore(2)
        ChatWorkflow._db_semaphore = asyncio.Semaphore(2)

        uow = MagicMock()
        uow.__aenter__.return_value = uow
        uow.__aexit__.return_value = None

        dispatcher = AsyncMock()

        with (
            patch(
                "backend.application.chat.web_stream_workflow.SessionManager"
            ) as mock_sm,
            patch(
                "backend.application.chat.web_stream_workflow.ChatMessageUpdater"
            ) as mock_up,
        ):
            mock_sm_inst = mock_sm.return_value
            mock_sm_inst.ensure_session = AsyncMock(
                return_value=MagicMock(id=uuid.uuid4(), title="test")
            )
            mock_sm_inst.create_user_message = AsyncMock()
            mock_sm_inst.create_assistant_message = AsyncMock(
                return_value=MagicMock(id=uuid.uuid4())
            )
            mock_sm_inst.get_session_messages = AsyncMock(return_value=[])

            mock_up_inst = mock_up.return_value
            mock_up_inst.update_as_success = AsyncMock()
            mock_up_inst.update_as_failed = AsyncMock()

            workflow = ChatWorkflow(uow, dispatcher)

            user_id = uuid.uuid4()
            start_time = time.time()

            async def consume_stream():
                async for _ in workflow.handle_query_stream(
                    ChatQueryCommand(
                        user_id=user_id,
                        query_text="hello",
                    )
                ):
                    pass

            tasks = [consume_stream() for _ in range(4)]
            await asyncio.gather(*tasks)

            end_time = time.time()
            total_time = end_time - start_time
            assert 0.9 <= total_time <= 1.5
