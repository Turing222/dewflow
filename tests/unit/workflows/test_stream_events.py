from backend.application.chat.stream_events import (
    decode_stream_event,
    encode_chunk_event,
    encode_done_event,
    encode_error_event,
)


def test_stream_events_round_trip_structured_payloads():
    assert decode_stream_event(encode_chunk_event("hello")) == {
        "type": "chunk",
        "content": "hello",
    }
    assert decode_stream_event(encode_error_event("failed")) == {
        "type": "error",
        "message": "failed",
    }
    assert decode_stream_event(encode_done_event()) == {"type": "done"}


def test_stream_events_accept_legacy_payloads():
    assert decode_stream_event("raw chunk") == {
        "type": "chunk",
        "content": "raw chunk",
    }
    assert decode_stream_event("[ERROR]failed") == {
        "type": "error",
        "message": "failed",
    }
    assert decode_stream_event("[DONE]") == {"type": "done"}

