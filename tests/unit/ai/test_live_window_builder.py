"""LiveWindowBuilder 单元测试。"""

import pytest

from backend.ai.core.live_window_builder import LiveWindowBuilder, LiveWindowResult
from backend.ai.core.token_counter import count_messages_tokens


@pytest.fixture
def builder():
    return LiveWindowBuilder(recent_rounds=2, snippet_chars=80, summary_max_chars=500)


@pytest.fixture
def history():
    """3 轮对话历史。"""
    return [
        {"role": "user", "content": "第一轮用户问题"},
        {"role": "assistant", "content": "第一轮助手回答"},
        {"role": "user", "content": "第二轮用户问题"},
        {"role": "assistant", "content": "第二轮助手回答"},
        {"role": "user", "content": "第三轮用户问题"},
        {"role": "assistant", "content": "第三轮助手回答"},
    ]


class TestWindowResult:
    def test_defaults(self):
        result = LiveWindowResult()
        assert result.exact_messages == []
        assert result.bridge_summary == ""
        assert result.overflow_compressed is False


class TestBuild:
    def test_empty_history(self, builder):
        result = builder.build([], "query", 1000, "gpt-4")
        assert result.exact_messages == []
        assert result.bridge_summary == ""

    def test_keeps_recent_rounds(self, builder, history):
        budget = count_messages_tokens(history, "gpt-4") + 100
        result = builder.build(history, "新问题", budget, "gpt-4")
        # recent_rounds=2，最近 2 轮保留为 exact_messages
        assert len(result.exact_messages) == 4

    def test_generates_bridge_summary_for_old_rounds(self, builder, history):
        budget = count_messages_tokens(history, "gpt-4") + 100
        result = builder.build(history, "新问题", budget, "gpt-4")
        assert result.bridge_summary

    def test_excludes_duplicate_current_query(self, builder, history):
        duplicate = list(history) + [{"role": "user", "content": "当前问题"}]
        budget = count_messages_tokens(duplicate, "gpt-4") + 100
        result = builder.build(duplicate, "当前问题", budget, "gpt-4")
        assert result.exact_messages[-1]["content"] != "当前问题"

    def test_drops_old_rounds_when_over_budget(self, builder, history):
        tight_budget = count_messages_tokens(history[-4:], "gpt-4") - 1
        result = builder.build(history, "新问题", tight_budget, "gpt-4")
        assert len(result.exact_messages) < 4
        assert result.overflow_compressed

    def test_all_history_within_budget(self, builder, history):
        huge_budget = 100000
        result = builder.build(history, "新问题", huge_budget, "gpt-4")
        assert len(result.exact_messages) == 4
        assert not result.overflow_compressed

    def test_zero_recent_rounds(self, history):
        builder = LiveWindowBuilder(recent_rounds=0)
        budget = count_messages_tokens(history, "gpt-4") + 100
        result = builder.build(history, "新问题", budget, "gpt-4")
        assert result.exact_messages == []
        assert result.bridge_summary

    def test_zero_budget(self, builder, history):
        result = builder.build(history, "新问题", 0, "gpt-4")
        assert result.exact_messages == []
        assert result.overflow_compressed
