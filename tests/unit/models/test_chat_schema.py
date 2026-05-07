import pytest
from pydantic import ValidationError

from backend.models.schemas.chat_schema import QuerySentRequest


def test_query_request_extra_body_accepts_thinking_mode():
    request = QuerySentRequest.model_validate(
        {
            "query": "你好",
            "extra_body": {"thinking": {"type": "disabled"}},
        }
    )

    assert request.extra_body is not None
    assert request.extra_body.to_provider_dict() == {
        "thinking": {"type": "disabled"}
    }


def test_query_request_extra_body_rejects_unknown_keys():
    with pytest.raises(ValidationError):
        QuerySentRequest.model_validate(
            {
                "query": "你好",
                "extra_body": {"temperature": 0.7},
            }
        )
