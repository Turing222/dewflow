"""RAG eval snapshot comparison.

职责：比较两份评测快照的聚合指标、分类指标和样本退化。
边界：只读取本地 JSON 报告并输出差异；不执行评测、不修改 baseline。
副作用：可选写出本地 JSON diff 报告。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from evals.common import write_eval_report

SUMMARY_KEYS = (
    "planner_accuracy",
    "should_use_rag_accuracy",
    "retrieval_mode_accuracy",
    "rerank_decision_accuracy",
    "hit_at_k",
    "recall_at_k",
    "mrr",
    "retrieval_hit_rate",
    "avg_total_latency_ms",
    "avg_llm_latency_ms",
    "avg_plan_latency_ms",
    "avg_planner_latency_ms",
    "error_count",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare two RAG eval reports")
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--latency-regression-ms",
        type=float,
        default=250.0,
        help="Per-sample latency increase that counts as degradation",
    )
    return parser.parse_args()


def load_report(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def compare_reports(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    latency_regression_ms: float = 250.0,
) -> dict[str, Any]:
    warnings = _warnings(baseline, candidate)
    return {
        "baseline": _run_info(baseline),
        "candidate": _run_info(candidate),
        "warnings": warnings,
        "summary_delta": _summary_delta(baseline, candidate),
        "missing_metrics": _missing_summary_metrics(baseline, candidate),
        "category_delta": _category_delta(baseline, candidate),
        "degraded_samples": _degraded_samples(
            baseline,
            candidate,
            latency_regression_ms=latency_regression_ms,
        ),
    }


def _warnings(baseline: dict[str, Any], candidate: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    baseline_run = baseline.get("run") or {}
    candidate_run = candidate.get("run") or {}
    if not baseline_run:
        warnings.append("baseline report has no run metadata")
    if not candidate_run:
        warnings.append("candidate report has no run metadata")
    if baseline_run.get("dataset_hash") != candidate_run.get("dataset_hash"):
        warnings.append("dataset_hash differs between baseline and candidate")
    return warnings


def _run_info(report: dict[str, Any]) -> dict[str, Any]:
    run = report.get("run") or {}
    return {
        "id": run.get("id"),
        "kind": run.get("kind"),
        "dataset_hash": run.get("dataset_hash"),
        "git_commit": run.get("git_commit"),
        "config": run.get("config", {}),
    }


def _summary_delta(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, float]:
    baseline_values = _flatten_summary(baseline.get("summary", {}))
    candidate_values = _flatten_summary(candidate.get("summary", {}))
    keys = set(SUMMARY_KEYS)
    keys.update(k for k in baseline_values if k.startswith("ragas_scores."))
    keys.update(k for k in candidate_values if k.startswith("ragas_scores."))
    return _numeric_delta(baseline_values, candidate_values, keys)


def _missing_summary_metrics(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
) -> list[dict[str, str]]:
    baseline_values = _flatten_summary(baseline.get("summary", {}))
    candidate_values = _flatten_summary(candidate.get("summary", {}))
    keys = set(SUMMARY_KEYS)
    keys.update(k for k in baseline_values if k.startswith("ragas_scores."))
    keys.update(k for k in candidate_values if k.startswith("ragas_scores."))
    missing: list[dict[str, str]] = []
    for key in sorted(keys):
        if key in baseline_values and key not in candidate_values:
            missing.append({"metric": key, "side": "candidate"})
        elif key not in baseline_values and key in candidate_values:
            missing.append({"metric": key, "side": "baseline"})
    return missing


def _flatten_summary(summary: dict[str, Any]) -> dict[str, Any]:
    flattened = dict(summary)
    for key, value in (summary.get("ragas_scores") or {}).items():
        flattened[f"ragas_scores.{key}"] = value
    return flattened


def _category_delta(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, dict[str, float]]:
    baseline_categories = (baseline.get("summary") or {}).get("per_category") or {}
    candidate_categories = (candidate.get("summary") or {}).get("per_category") or {}
    result: dict[str, dict[str, float]] = {}
    for category in sorted(set(baseline_categories) & set(candidate_categories)):
        baseline_values = baseline_categories[category]
        candidate_values = candidate_categories[category]
        result[category] = _numeric_delta(
            baseline_values,
            candidate_values,
            set(baseline_values) | set(candidate_values),
        )
    return result


def _numeric_delta(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    keys: set[str],
) -> dict[str, float]:
    result: dict[str, float] = {}
    for key in sorted(keys):
        if isinstance(baseline.get(key), int | float) and isinstance(
            candidate.get(key), int | float
        ):
            result[key] = float(candidate[key]) - float(baseline[key])
    return result


def _degraded_samples(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    latency_regression_ms: float,
) -> list[dict[str, Any]]:
    baseline_by_id = _details_by_id(baseline)
    candidate_by_id = _details_by_id(candidate)
    degraded: list[dict[str, Any]] = []
    for sample_id in sorted(set(baseline_by_id) & set(candidate_by_id)):
        reasons = _sample_degradation_reasons(
            baseline_by_id[sample_id],
            candidate_by_id[sample_id],
            latency_regression_ms=latency_regression_ms,
        )
        if reasons:
            degraded.append({"id": sample_id, "reasons": reasons})
    return degraded


def _details_by_id(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row["id"]): row
        for row in report.get("details", [])
        if isinstance(row, dict) and row.get("id") is not None
    }


def _sample_degradation_reasons(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    latency_regression_ms: float,
) -> list[dict[str, Any]]:
    reasons: list[dict[str, Any]] = []
    _append_lower_score_reasons(reasons, baseline, candidate)
    if not baseline.get("error_message") and candidate.get("error_message"):
        reasons.append(
            {"metric": "error_message", "candidate": candidate["error_message"]}
        )
    baseline_latency = baseline.get("total_latency_ms") or baseline.get(
        "sample_latency_ms"
    )
    candidate_latency = candidate.get("total_latency_ms") or candidate.get(
        "sample_latency_ms"
    )
    if isinstance(baseline_latency, int | float) and isinstance(
        candidate_latency, int | float
    ):
        delta = float(candidate_latency) - float(baseline_latency)
        if delta >= latency_regression_ms:
            reasons.append({"metric": "latency_ms", "delta": delta})
    return reasons


def _append_lower_score_reasons(
    reasons: list[dict[str, Any]],
    baseline: dict[str, Any],
    candidate: dict[str, Any],
) -> None:
    for metric in (
        "planner_match",
        "retrieval_hit",
        "hit_at_k",
        "recall_at_k",
        "mrr",
        "ragas_faithfulness",
        "ragas_answer_relevancy",
        "ragas_answer_correctness",
    ):
        if isinstance(baseline.get(metric), int | float) and isinstance(
            candidate.get(metric), int | float
        ):
            delta = float(candidate[metric]) - float(baseline[metric])
            if delta < 0:
                reasons.append({"metric": metric, "delta": delta})


def main() -> None:
    args = parse_args()
    result = compare_reports(
        load_report(args.baseline),
        load_report(args.candidate),
        latency_regression_ms=args.latency_regression_ms,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.output:
        write_eval_report(args.output, result)


if __name__ == "__main__":
    main()
