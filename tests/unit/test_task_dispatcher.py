"""Unit tests for TaskDispatcher — verify parameters pass through to AsyncKicker."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from backend.infra.task_dispatcher import TASK_INGESTION, TASK_NONSTREAM, TASK_STREAM

_kiq_mock = AsyncMock()


def _make_mock_kicker(**kwargs):
    """Factory that returns a mock kicker whose .kiq() is the shared _kiq_mock."""
    kicker = AsyncMock()
    kicker.kiq = _kiq_mock
    return kicker


@pytest.fixture(autouse=True)
def _reset_kiq_mock():
    _kiq_mock.reset_mock()
    _kiq_mock.side_effect = None


@pytest.mark.asyncio
async def test_enqueue_stream_passes_params_through():
    from backend.infra.task_dispatcher import TaskDispatcher

    dispatcher = TaskDispatcher()
    payload = {"session_id": str(uuid.uuid4()), "query_text": "hello"}
    channel = "stream:test"
    trace_ctx = {"traceparent": "00-test"}
    msg_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    lock_key = "lock:test"

    with patch(
        "backend.infra.task_dispatcher.AsyncKicker",
        side_effect=_make_mock_kicker,
    ):
        await dispatcher.enqueue_stream(
            generation_payload=payload,
            channel=channel,
            trace_context=trace_ctx,
            assistant_message_id=msg_id,
            user_id=user_id,
            idempotency_lock_key=lock_key,
        )

    _kiq_mock.assert_awaited_once_with(
        payload, channel, trace_ctx, msg_id, user_id, lock_key
    )


@pytest.mark.asyncio
async def test_enqueue_nonstream_passes_params_and_returns_result():
    from backend.infra.task_dispatcher import TaskDispatcher

    dispatcher = TaskDispatcher()
    payload = {"session_id": str(uuid.uuid4()), "query_text": "hello"}
    trace_ctx = {"traceparent": "00-test"}
    msg_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    lock_key = "lock:test"
    expected_result = {"success": True, "content": "answer"}

    from types import SimpleNamespace

    mock_tq_result = SimpleNamespace(return_value=expected_result)
    mock_task = AsyncMock()
    mock_task.wait_result = AsyncMock(return_value=mock_tq_result)

    def _kicker_with_result(*args, **kwargs):
        kicker = AsyncMock()
        kicker.kiq = AsyncMock(return_value=mock_task)
        return kicker

    with patch(
        "backend.infra.task_dispatcher.AsyncKicker",
        side_effect=_kicker_with_result,
    ):
        result = await dispatcher.enqueue_nonstream(
            generation_payload=payload,
            trace_context=trace_ctx,
            assistant_message_id=msg_id,
            user_id=user_id,
            idempotency_lock_key=lock_key,
        )

    mock_task.wait_result.assert_awaited_once()
    assert result == expected_result


@pytest.mark.asyncio
async def test_enqueue_ingestion_passes_params_through():
    from backend.infra.task_dispatcher import TaskDispatcher

    dispatcher = TaskDispatcher()
    file_id = str(uuid.uuid4())
    task_id = str(uuid.uuid4())
    trace_ctx = {"traceparent": "00-test"}

    with patch(
        "backend.infra.task_dispatcher.AsyncKicker",
        side_effect=_make_mock_kicker,
    ):
        await dispatcher.enqueue_ingestion(
            file_id=file_id,
            task_id=task_id,
            trace_context=trace_ctx,
        )

    _kiq_mock.assert_awaited_once_with(file_id, task_id, trace_ctx)


@pytest.mark.asyncio
async def test_task_name_constants_match_expected():
    """Ensure task name constants are not accidentally changed."""
    assert TASK_STREAM == "generate_llm_stream"
    assert TASK_NONSTREAM == "generate_llm_nonstream"
    assert TASK_INGESTION == "ingest_knowledge_file"
