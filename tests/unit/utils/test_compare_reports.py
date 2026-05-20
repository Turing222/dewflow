"""Evals report comparison unit tests.

职责：验证评测快照对比的指标 delta、warning 和样本退化识别。
边界：使用内存字典，不执行真实评测；副作用：无。
"""

import pytest

from evals.compare_reports import compare_reports


def test_compare_reports_computes_nested_ragas_delta() -> None:
    baseline = _report(
        dataset_hash="same",
        summary={
            "ragas_scores": {"faithfulness": 0.7},
            "error_count": 0,
        },
    )
    candidate = _report(
        dataset_hash="same",
        summary={
            "ragas_scores": {"faithfulness": 0.8},
            "error_count": 1,
        },
    )

    result = compare_reports(baseline, candidate)

    assert result["summary_delta"]["ragas_scores.faithfulness"] == pytest.approx(0.1)
    assert result["summary_delta"]["error_count"] == 1.0
    assert result["warnings"] == []


def test_compare_reports_detects_degraded_samples() -> None:
    baseline = _report(
        dataset_hash="same",
        details=[
            {
                "id": "case-1",
                "ragas_faithfulness": 0.9,
                "retrieval_hit": 1.0,
                "total_latency_ms": 100,
            }
        ],
    )
    candidate = _report(
        dataset_hash="same",
        details=[
            {
                "id": "case-1",
                "ragas_faithfulness": 0.7,
                "retrieval_hit": 0.0,
                "total_latency_ms": 500,
            }
        ],
    )

    result = compare_reports(baseline, candidate, latency_regression_ms=250)

    reasons = result["degraded_samples"][0]["reasons"]
    assert {reason["metric"] for reason in reasons} == {
        "ragas_faithfulness",
        "retrieval_hit",
        "latency_ms",
    }


def test_compare_reports_warns_on_dataset_hash_mismatch() -> None:
    baseline = _report(dataset_hash="old")
    candidate = _report(dataset_hash="new")

    result = compare_reports(baseline, candidate)

    assert "dataset_hash differs between baseline and candidate" in result["warnings"]


def test_compare_reports_reports_missing_metrics() -> None:
    baseline = _report(
        dataset_hash="same",
        summary={"ragas_scores": {"faithfulness": 0.7}},
    )
    candidate = _report(dataset_hash="same", summary={})

    result = compare_reports(baseline, candidate)

    assert result["missing_metrics"] == [
        {"metric": "ragas_scores.faithfulness", "side": "candidate"}
    ]


def test_compare_reports_handles_empty_reports() -> None:
    result = compare_reports({}, {})

    assert result["summary_delta"] == {}
    assert result["category_delta"] == {}
    assert result["degraded_samples"] == []
    assert result["missing_metrics"] == []
    assert "baseline report has no run metadata" in result["warnings"]
    assert "candidate report has no run metadata" in result["warnings"]


def test_compare_reports_ignores_details_without_id() -> None:
    baseline = _report(
        details=[
            {
                "ragas_faithfulness": 0.9,
                "total_latency_ms": 100,
            }
        ],
    )
    candidate = _report(
        details=[
            {
                "ragas_faithfulness": 0.1,
                "total_latency_ms": 1000,
            }
        ],
    )

    result = compare_reports(baseline, candidate, latency_regression_ms=250)

    assert result["degraded_samples"] == []


def test_compare_reports_ignores_one_sided_categories() -> None:
    baseline = _report(
        summary={
            "per_category": {
                "fact": {"samples": 1, "mrr": 0.5},
            }
        }
    )
    candidate = _report(
        summary={
            "per_category": {
                "summary": {"samples": 1, "mrr": 0.9},
            }
        }
    )

    result = compare_reports(baseline, candidate)

    assert result["category_delta"] == {}


def _report(
    *,
    dataset_hash: str = "same",
    summary: dict | None = None,
    details: list[dict] | None = None,
) -> dict:
    return {
        "run": {
            "id": f"run-{dataset_hash}",
            "kind": "answer",
            "dataset_hash": dataset_hash,
            "git_commit": "abc",
            "config": {},
        },
        "summary": summary or {},
        "details": details or [],
    }
