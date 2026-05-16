"""Context budgeter unit tests.

职责：验证上下文预算分配、丢弃和校验规则；边界：使用纯内存 block，不调用 tokenizer 外部服务；副作用：无。
"""

import pytest

from backend.ai.core.context_budgeter import (
    PRIORITY_BRIDGE,
    PRIORITY_HISTORY,
    PRIORITY_QUERY,
    PRIORITY_RAG_CHUNKS,
    PRIORITY_SYSTEM,
    BudgetBlock,
    ContextBudgeter,
)


@pytest.fixture
def budgeter() -> ContextBudgeter:
    return ContextBudgeter(max_context_tokens=4096, reserved_response_tokens=1024, model_name="gpt-4")


@pytest.fixture
def tight_budgeter() -> ContextBudgeter:
    return ContextBudgeter(max_context_tokens=200, reserved_response_tokens=50, model_name="gpt-4")


class TestBudgetBlock:
    def test_defaults(self) -> None:
        block = BudgetBlock(name="test")
        assert block.priority == PRIORITY_HISTORY
        assert block.content == ""
        assert block.token_estimate == 0
        assert block.allocated == 0
        assert block.compressible is False
        assert block.required is False


class TestContextBudgeterProperties:
    def test_total_budget(self, budgeter) -> None:
        assert budgeter.total_budget == 4096 - 1024


class TestAllocate:
    def test_allocates_required_blocks_first(self, budgeter) -> None:
        blocks = [
            BudgetBlock(name="system", priority=PRIORITY_SYSTEM, content="X" * 400, required=True),
            BudgetBlock(name="query", priority=PRIORITY_QUERY, content="Y" * 100, required=True),
        ]
        budgeter.allocate(blocks)
        assert all(b.allocated > 0 for b in blocks)

    def test_drops_low_priority_when_over_budget(self, tight_budgeter) -> None:
        blocks = [
            BudgetBlock(name="system", priority=PRIORITY_SYSTEM, content="X" * 400, required=True, token_estimate=120),
            BudgetBlock(name="history", priority=PRIORITY_HISTORY, content="Z" * 2000, token_estimate=600),
        ]
        result = tight_budgeter.allocate(blocks)
        system_block = next(b for b in result if b.name == "system")
        history_block = next(b for b in result if b.name == "history")
        assert system_block.allocated > 0
        assert history_block.allocated == 0

    def test_marks_compressible_when_over_budget(self, tight_budgeter) -> None:
        blocks = [
            BudgetBlock(name="system", priority=PRIORITY_SYSTEM, content="X" * 400, required=True, token_estimate=120),
            BudgetBlock(
                name="history",
                priority=PRIORITY_HISTORY,
                content="Z" * 2000,
                token_estimate=600,
                compressible=True,
            ),
        ]
        result = tight_budgeter.allocate(blocks)
        history = next(b for b in result if b.name == "history")
        assert history.allocated <= history.token_estimate

    def test_priority_order_respected(self, budgeter) -> None:
        blocks = [
            BudgetBlock(name="bridge", priority=PRIORITY_BRIDGE, content="A" * 100, token_estimate=30),
            BudgetBlock(name="rag", priority=PRIORITY_RAG_CHUNKS, content="B" * 1000, token_estimate=300),
        ]
        result = budgeter.allocate(blocks)
        rag = next(b for b in result if b.name == "rag")
        bridge = next(b for b in result if b.name == "bridge")
        # RAG 优先级高于 bridge，应该分配到更多或至少相等
        assert rag.allocated >= bridge.allocated or bridge.allocated == 0

    def test_all_fit_no_drops(self, budgeter) -> None:
        blocks = [
            BudgetBlock(name="system", priority=PRIORITY_SYSTEM, content="S" * 200, required=True, token_estimate=60),
            BudgetBlock(name="query", priority=PRIORITY_QUERY, content="Q" * 50, required=True, token_estimate=20),
            BudgetBlock(name="rag", priority=PRIORITY_RAG_CHUNKS, content="R" * 400, token_estimate=120),
        ]
        result = budgeter.allocate(blocks)
        assert all(b.allocated >= b.token_estimate for b in result)


class TestValidate:
    def test_validate_ok(self, budgeter) -> None:
        messages = [
            {"role": "system", "content": "简短 system prompt"},
            {"role": "user", "content": "简短问题"},
        ]
        ok, actual = budgeter.validate(messages)
        assert ok
        assert actual > 0

    def test_validate_over_budget(self, tight_budgeter) -> None:
        messages = [{"role": "user", "content": "X" * 10000}]
        ok, actual = tight_budgeter.validate(messages)
        assert not ok

    def test_validate_with_explicit_tokens(self, budgeter) -> None:
        ok, actual = budgeter.validate([], actual_tokens=5000)
        assert not ok
        assert actual == 5000
