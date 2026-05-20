"""RAG planner decision evaluation.

职责：评估 RAG planner 的结构化决策是否符合数据集期望。
边界：不执行检索、不生成回答、不调用 Ragas；仅调用 RAGPlanningService。
副作用：输出本地 JSON 评测报告。
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from backend.services.rag_planning_service import (
    RAG_PLANNER_FALLBACK_REASON,
)
from evals.common import (
    build_run_metadata,
    create_rag_planner,
    load_samples,
    safe_div,
    summarize_by_category,
    write_eval_report,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate RAG planner decisions")
    parser.add_argument(
        "--dataset", type=Path, required=True, help="Path to JSONL dataset"
    )
    parser.add_argument(
        "--planner-provider",
        default=None,
        help="Optional planner LLM provider override",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("evals/reports/rag_planner_report.json"),
        help="Output report path",
    )
    return parser.parse_args()


def _score_plan(
    plan: Any, expected_plan: dict[str, Any] | None
) -> dict[str, float | None]:
    if not expected_plan:
        return {
            "planner_match": None,
            "should_use_rag_match": None,
            "retrieval_mode_match": None,
            "rerank_decision_match": None,
        }

    checks: dict[str, bool] = {}
    if "should_use_rag" in expected_plan:
        checks["should_use_rag_match"] = _strict_bool_match(
            plan.should_use_rag,
            expected_plan["should_use_rag"],
        )
    if "retrieval_mode" in expected_plan:
        checks["retrieval_mode_match"] = str(plan.retrieval_mode) == str(
            expected_plan["retrieval_mode"]
        )
    if "use_rerank" in expected_plan:
        checks["rerank_decision_match"] = _strict_bool_match(
            plan.use_rerank,
            expected_plan["use_rerank"],
        )

    planner_match = all(checks.values()) if checks else None
    return {
        "planner_match": float(planner_match) if planner_match is not None else None,
        "should_use_rag_match": _float_match(checks.get("should_use_rag_match")),
        "retrieval_mode_match": _float_match(checks.get("retrieval_mode_match")),
        "rerank_decision_match": _float_match(checks.get("rerank_decision_match")),
    }


def _float_match(value: bool | None) -> float | None:
    return float(value) if value is not None else None


def _strict_bool_match(actual: Any, expected: Any) -> bool:
    return (
        isinstance(actual, bool) and isinstance(expected, bool) and actual is expected
    )


async def run(args: argparse.Namespace) -> None:
    samples = load_samples(args.dataset)
    run_started_at = time.perf_counter()
    planner = create_rag_planner(args.planner_provider)
    rows: list[dict[str, Any]] = []
    fallback_count = 0
    latency_total = 0.0

    for sample in samples:
        started_at = time.perf_counter()
        error_message: str | None = None
        try:
            plan = await planner.plan(
                query_text=sample.query,
                conversation_history=[],
                kb_id=sample.kb_id,
            )
        except Exception as exc:
            error_message = str(exc)
            plan = None

        latency_ms = int((time.perf_counter() - started_at) * 1000)
        latency_total += latency_ms
        plan_payload = plan.model_dump() if plan is not None else {}
        is_fallback = bool(plan and plan.reason == RAG_PLANNER_FALLBACK_REASON)
        fallback_count += int(is_fallback)
        scores = _score_plan(plan, sample.expected_plan) if plan else {}

        rows.append(
            {
                "id": sample.id,
                "category": sample.category,
                "query": sample.query,
                "kb_id": str(sample.kb_id) if sample.kb_id else None,
                "expected_plan": sample.expected_plan,
                "plan": plan_payload,
                "plan_latency_ms": latency_ms,
                "planner_fallback": is_fallback,
                "error_message": error_message,
                **scores,
            }
        )

    total = len(samples)
    summary = {
        "samples": total,
        "planner_accuracy": _avg(rows, "planner_match"),
        "should_use_rag_accuracy": _avg(rows, "should_use_rag_match"),
        "retrieval_mode_accuracy": _avg(rows, "retrieval_mode_match"),
        "rerank_decision_accuracy": _avg(rows, "rerank_decision_match"),
        "avg_plan_latency_ms": safe_div(latency_total, total),
        "fallback_rate": safe_div(fallback_count, total),
        "runtime_sec": round(time.perf_counter() - run_started_at, 3),
        "per_category": summarize_by_category(
            rows,
            [
                "planner_match",
                "should_use_rag_match",
                "retrieval_mode_match",
                "rerank_decision_match",
                "plan_latency_ms",
            ],
        ),
    }
    report = {
        "run": build_run_metadata(
            kind="planner",
            dataset_path=args.dataset,
            config={
                "cli_args": {
                    "planner_provider": args.planner_provider,
                    "output": str(args.output),
                },
                "models": {"planner_provider": args.planner_provider},
            },
        ),
        "summary": summary,
        "details": rows,
    }
    write_eval_report(args.output, report)
    print("\nRAG Planner Eval Done")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Report saved to: {args.output}")


def _avg(rows: list[dict[str, Any]], key: str) -> float:
    values = [float(row[key]) for row in rows if row.get(key) is not None]
    return safe_div(sum(values), len(values))


def main() -> None:
    import asyncio

    asyncio.run(run(parse_args()))


if __name__ == "__main__":
    main()
