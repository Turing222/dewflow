"""LiveWindowBuilder memory context tests — history window construction and query deduplication.

职责：验证 LiveWindowBuilder 的当前 query 去重、轮次分割和摘要字符限制；
边界：纯内存计算，不依赖外部服务；副作用：无。
"""

from backend.ai.core.live_window_builder import LiveWindowBuilder


def test_exclude_latest_query_when_duplicate() -> None:
    history = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好，我在。"},
        {"role": "user", "content": "本轮问题"},
    ]

    result = LiveWindowBuilder._exclude_latest_query(history, current_query="本轮问题")

    assert result == [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好，我在。"},
    ]


def test_build_splits_recent_rounds_and_summary() -> None:
    builder = LiveWindowBuilder(
        recent_rounds=1, snippet_chars=60, summary_max_chars=1000
    )

    history = [
        {"role": "user", "content": "第一轮问题"},
        {"role": "assistant", "content": "第一轮回答"},
        {"role": "user", "content": "第二轮问题"},
        {"role": "assistant", "content": "第二轮回答"},
        {"role": "user", "content": "第三轮问题"},
    ]

    result = builder.build(
        history=history,
        current_query="第三轮问题",
        budget_tokens=10000,
        model="gpt-4",
    )

    assert result.exact_messages == [
        {"role": "user", "content": "第二轮问题"},
        {"role": "assistant", "content": "第二轮回答"},
    ]
    assert "第一轮问题" in result.bridge_summary
    assert "第一轮回答" in result.bridge_summary
    assert "第二轮问题" not in result.bridge_summary


def test_build_rounds_summary_respects_max_chars() -> None:
    builder = LiveWindowBuilder(snippet_chars=30, summary_max_chars=200)

    rounds = [
        [
            {"role": "user", "content": f"U{i}"},
            {"role": "assistant", "content": f"A{i}"},
        ]
        for i in range(5)
    ]

    summary_text = builder._build_rounds_summary(rounds)

    assert len(summary_text) <= 200
    assert summary_text != ""
    assert "\n" in summary_text
