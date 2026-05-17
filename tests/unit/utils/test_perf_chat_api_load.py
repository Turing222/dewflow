"""Perf chat API load runner unit tests.

职责：验证性能 runner 的 profile 解析、聚合报告和 Ragas 隔离约束。
边界：不发真实 HTTP 请求，不启动服务；副作用：仅使用 tmp_path 写临时数据集。
"""

from pathlib import Path

import httpx
import pytest

from perf.chat_api_load import (
    PerfSample,
    Scenario,
    build_report,
    choose_sample,
    choose_scenario,
    ensure_dataset_exists,
    is_acceptable_register_response,
    load_perf_samples,
    load_profile,
    parse_args,
    percentile,
    summarize_details,
)


def test_load_profile_parses_weighted_scenarios() -> None:
    profile = load_profile(Path("perf/profiles/enterprise_smoke.json"))

    assert profile.name == "enterprise_smoke"
    assert profile.concurrency_limit == 4
    assert {scenario.name for scenario in profile.scenarios} == {
        "single_turn_rag",
        "multi_turn_rag",
        "long_query",
        "empty_retrieval",
        "health_check",
    }


def test_load_profile_reports_missing_required_fields(tmp_path: Path) -> None:
    profile_path = tmp_path / "bad_profile.json"
    profile_path.write_text('{"duration_sec": 1}', encoding="utf-8")

    with pytest.raises(ValueError, match="profile.arrival_rate_rps is required"):
        load_profile(profile_path)


def test_load_perf_samples_uses_lightweight_eval_fields(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text(
        '{"id":"case-1","query":"hello","kb_id":null,'
        '"category":"general","must_refuse":true}\n',
        encoding="utf-8",
    )

    samples = load_perf_samples(dataset)

    assert len(samples) == 1
    assert samples[0].id == "case-1"
    assert samples[0].query == "hello"
    assert samples[0].kb_id is None
    assert samples[0].must_refuse is True


def test_ensure_dataset_exists_reports_profile_path_error(tmp_path: Path) -> None:
    missing_dataset = tmp_path / "missing.jsonl"

    with pytest.raises(FileNotFoundError, match="Check profile.dataset.path"):
        ensure_dataset_exists(missing_dataset)


@pytest.mark.parametrize("status_code", [200, 201, 409])
def test_is_acceptable_register_response_accepts_success_and_conflict(
    status_code: int,
) -> None:
    response = httpx.Response(status_code=status_code, json={})

    assert is_acceptable_register_response(response) is True


@pytest.mark.parametrize(
    "code",
    [
        "USERNAME_ALREADY_REGISTERED",
        "EMAIL_ALREADY_REGISTERED",
        "USER_ALREADY_REGISTERED",
    ],
)
def test_is_acceptable_register_response_accepts_known_registration_conflicts(
    code: str,
) -> None:
    response = httpx.Response(status_code=422, json={"code": code})

    assert is_acceptable_register_response(response) is True


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(status_code=400, json={"code": "BAD_REQUEST"}),
        httpx.Response(status_code=422, json={"code": "VALIDATION_ERROR"}),
        httpx.Response(status_code=422, content=b"not-json"),
        httpx.Response(status_code=500, json={"code": "SERVER_ERROR"}),
    ],
)
def test_is_acceptable_register_response_rejects_unexpected_failures(
    response: httpx.Response,
) -> None:
    assert is_acceptable_register_response(response) is False


def test_choose_scenario_ignores_zero_weight_and_rejects_all_zero() -> None:
    disabled = _scenario("disabled", weight=0)
    enabled = _scenario("enabled", weight=1)

    assert {choose_scenario((disabled, enabled)).name for _ in range(20)} == {"enabled"}

    with pytest.raises(ValueError, match="positive weight"):
        choose_scenario((disabled,))


def test_choose_sample_supports_inline_and_dataset_sources() -> None:
    inline = _scenario(
        "long_query",
        query_source="inline",
        queries=("inline query",),
        kb_id="kb-inline",
    )
    dataset = _scenario("dataset", kb_id="kb-override")
    samples = [
        PerfSample(
            id="case-1",
            query="dataset query",
            kb_id=None,
            category="general",
            must_refuse=True,
        )
    ]

    inline_sample = choose_sample(inline, samples)
    dataset_sample = choose_sample(dataset, samples)

    assert inline_sample.query == "inline query"
    assert inline_sample.kb_id == "kb-inline"
    assert inline_sample.category == "long_query"
    assert dataset_sample.query == "dataset query"
    assert dataset_sample.kb_id == "kb-override"
    assert dataset_sample.must_refuse is True


def test_summarize_details_reports_latency_and_behavior_signals() -> None:
    rows = [
        _detail("single_turn_rag", latency_ms=100, success=True),
        _detail(
            "single_turn_rag", latency_ms=300, success=False, error_type="http_500"
        ),
        _detail("health_check", latency_ms=50, success=True, answer_length=0),
    ]

    summary = summarize_details(rows, runtime_sec=2.0)

    assert summary["requests"] == 3
    assert summary["success_count"] == 2
    assert summary["failure_count"] == 1
    assert summary["error_rate"] == 1 / 3
    assert summary["actual_rps"] == 1.5
    assert summary["p50_ms"] == 100
    assert summary["p95_ms"] == 300
    assert summary["max_ms"] == 300
    assert summary["avg_retrieved_count"] == 2
    assert summary["empty_answer_rate"] == 0


def test_parse_args_exposes_seed_and_default_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["chat_api_load.py", "--seed", "42"],
    )

    args = parse_args()

    assert args.profile == Path("perf/profiles/enterprise_smoke.json")
    assert args.output == Path("perf/reports/chat_api_load_report.json")
    assert args.seed == 42


def test_build_report_contains_no_ragas_fields() -> None:
    profile = load_profile(Path("perf/profiles/enterprise_smoke.json"))
    report = build_report(
        profile=profile,
        base_url="http://example.test",
        runtime_sec=1.0,
        details=[_detail("single_turn_rag", latency_ms=100, success=True)],
    )

    assert set(report) == {"run", "summary", "scenarios", "errors", "details"}
    assert {"p50_ms", "p95_ms", "p99_ms", "error_rate", "actual_rps"}.issubset(
        report["summary"]
    )
    assert report["run"]["config"]["percentile_method"] == "nearest_rank"
    assert "actual_rps" not in report["scenarios"]["single_turn_rag"]
    assert "request_rate_estimate" in report["scenarios"]["single_turn_rag"]
    assert "ragas" not in str(report).lower()


def test_percentile_handles_empty_and_ordering() -> None:
    assert percentile([], 95) == 0
    assert percentile([300, 100, 200], 50) == 200
    assert percentile([100, 200, 300, 400], 99) == 400


def _scenario(
    name: str,
    *,
    weight: int = 1,
    query_source: str = "dataset",
    queries: tuple[str, ...] = (),
    kb_id: str | None = None,
) -> Scenario:
    return Scenario(
        name=name,
        weight=weight,
        kind="chat",
        query_source=query_source,
        turns_min=1,
        turns_max=1,
        queries=queries,
        kb_id=kb_id,
    )


def _detail(
    scenario: str,
    *,
    latency_ms: int,
    success: bool,
    error_type: str | None = None,
    answer_length: int = 12,
) -> dict:
    return {
        "request_group_id": "group-1",
        "turn_index": 1,
        "scenario": scenario,
        "kind": "chat",
        "sample_id": "sample-1",
        "category": "general",
        "must_refuse": False,
        "status_code": 200 if success else 500,
        "success": success,
        "latency_ms": latency_ms,
        "retrieved_count": 2,
        "answer_length": answer_length,
        "empty_answer": False,
        "error_type": error_type,
        "error_message": "boom" if error_type else None,
    }
