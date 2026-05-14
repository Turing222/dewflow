"""Unit tests for TaskDispatcher — verify TaskIQ Redis messages."""

import json
import pickle
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from backend.infra.task_dispatcher import TASK_INGESTION, TASK_NONSTREAM, TASK_STREAM


class FakeRedis:
    def __init__(self, result_payload: bytes | None = None) -> None:
        self.lpush = AsyncMock()
        self.get = AsyncMock(return_value=result_payload)
        self.aclose = AsyncMock()


def _decode_lpush_message(redis_client: FakeRedis) -> dict:
    _, message = redis_client.lpush.await_args.args
    return json.loads(message.decode())


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

    redis_client = FakeRedis()

    with patch("backend.infra.task_dispatcher.redis.from_url", return_value=redis_client):
        await dispatcher.enqueue_stream(
            generation_payload=payload,
            channel=channel,
            trace_context=trace_ctx,
            assistant_message_id=msg_id,
            user_id=user_id,
            idempotency_lock_key=lock_key,
        )

    message = _decode_lpush_message(redis_client)
    assert message["task_name"] == TASK_STREAM
    assert message["args"] == [payload, channel, trace_ctx, msg_id, user_id, lock_key]


@pytest.mark.asyncio
async def test_enqueue_nonstream_passes_params_and_returns_result():
    from backend.infra.task_dispatcher import TaskDispatcher
    from backend.models.schemas.chat.payloads import GenerationResult

    dispatcher = TaskDispatcher()
    payload = {"session_id": str(uuid.uuid4()), "query_text": "hello"}
    trace_ctx = {"traceparent": "00-test"}
    msg_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    lock_key = "lock:test"
    expected_result = {"success": True, "content": "answer"}

    raw_result = pickle.dumps(
        {
            "is_err": False,
            "log": None,
            "return_value": expected_result,
            "execution_time": 0.1,
            "labels": {},
            "error": None,
        }
    )
    send_redis = FakeRedis()
    result_redis = FakeRedis(result_payload=raw_result)

    with patch(
        "backend.infra.task_dispatcher.redis.from_url",
        side_effect=[send_redis, result_redis],
    ):
        result = await dispatcher.enqueue_nonstream(
            generation_payload=payload,
            trace_context=trace_ctx,
            assistant_message_id=msg_id,
            user_id=user_id,
            idempotency_lock_key=lock_key,
        )

    message = _decode_lpush_message(send_redis)
    assert message["task_name"] == TASK_NONSTREAM
    assert message["args"] == [payload, trace_ctx, msg_id, user_id, lock_key]
    result_redis.get.assert_awaited_once_with(message["task_id"])
    assert isinstance(result, GenerationResult)
    assert result.success is True
    assert result.content == "answer"


@pytest.mark.asyncio
async def test_enqueue_ingestion_passes_params_through():
    from backend.infra.task_dispatcher import TaskDispatcher

    dispatcher = TaskDispatcher()
    file_id = str(uuid.uuid4())
    task_id = str(uuid.uuid4())
    trace_ctx = {"traceparent": "00-test"}

    redis_client = FakeRedis()

    with patch("backend.infra.task_dispatcher.redis.from_url", return_value=redis_client):
        await dispatcher.enqueue_ingestion(
            file_id=file_id,
            task_id=task_id,
            trace_context=trace_ctx,
        )

    message = _decode_lpush_message(redis_client)
    assert message["task_name"] == TASK_INGESTION
    assert message["args"] == [file_id, task_id, trace_ctx]


@pytest.mark.asyncio
async def test_task_name_constants_match_expected():
    """Ensure task name constants are not accidentally changed."""
    assert TASK_STREAM == "generate_llm_stream"
    assert TASK_NONSTREAM == "generate_llm_nonstream"
    assert TASK_INGESTION == "ingest_knowledge_file"
