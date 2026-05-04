from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.application.chat.web_stream_workflow import ChatWorkflow

pytestmark = [pytest.mark.asyncio, pytest.mark.smoke]


async def test_minimal_workflow_construction():
    uow = MagicMock()
    dispatcher = AsyncMock()
    workflow = ChatWorkflow(uow, dispatcher)

    assert workflow is not None
