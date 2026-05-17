"""Chat API load runner.

Responsibilities: run repeatable HTTP load profiles and emit machine-readable
performance reports.
Boundaries: does not run Ragas or LLM-as-judge evaluation.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import random
import time
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from evals.common import (
    build_run_metadata,
    load_samples,
    safe_div,
    write_eval_report,
)

REGISTER_PATH = "/api/v1/auth/register"
LOGIN_PATH = "/api/v1/auth/login"
QUERY_SENT_PATH = "/api/v1/chat/query_sent"
LIVE_PATH = "/api/v1/health_check/live"
REGISTER_CONFLICT_CODES = frozenset(
    {
        "USERNAME_ALREADY_REGISTERED",
        "EMAIL_ALREADY_REGISTERED",
        "USER_ALREADY_REGISTERED",
    }
)


@dataclass(frozen=True, slots=True)
class PerfSample:
    id: str
    query: str
    kb_id: str | None
    category: str
    must_refuse: bool


@dataclass(frozen=True, slots=True)
class Scenario:
    name: str
    weight: int
    kind: str
    query_source: str
    turns_min: int
    turns_max: int
    queries: tuple[str, ...]
    kb_id: str | None


@dataclass(frozen=True, slots=True)
class Profile:
    path: Path
    name: str
    duration_sec: float
    arrival_rate_rps: float
    concurrency_limit: int
    timeout_sec: float
    dataset_path: Path
    auth: dict[str, Any]
    scenarios: tuple[Scenario, ...]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run chat API HTTP load profile")
    parser.add_argument(
        "--profile",
        type=Path,
        default=Path("perf/profiles/enterprise_smoke.json"),
        help="Path to load profile JSON",
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("SMOKE_BASE_URL", "http://localhost:8000"),
        help="Target API base URL",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("perf/reports/chat_api_load_report.json"),
        help="Output report path",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Optional random seed for reproducible scenario/sample selection",
    )
    return parser.parse_args()


def load_profile(path: Path) -> Profile:
    payload = json.loads(path.read_text(encoding="utf-8"))
    for field_name in (
        "duration_sec",
        "arrival_rate_rps",
        "concurrency_limit",
        "scenarios",
    ):
        if field_name not in payload:
            raise ValueError(f"profile.{field_name} is required")
    dataset_payload = payload.get("dataset") or {}
    dataset_path = Path(dataset_payload.get("path") or "evals/dataset.sample.jsonl")
    scenarios = tuple(_parse_scenario(item) for item in payload["scenarios"])
    if not scenarios:
        raise ValueError("profile.scenarios must not be empty")
    return Profile(
        path=path,
        name=str(payload.get("name") or path.stem),
        duration_sec=float(payload["duration_sec"]),
        arrival_rate_rps=float(payload["arrival_rate_rps"]),
        concurrency_limit=max(1, int(payload["concurrency_limit"])),
        timeout_sec=float(payload.get("timeout_sec", 60.0)),
        dataset_path=dataset_path,
        auth=dict(payload.get("auth") or {}),
        scenarios=scenarios,
    )


def _parse_scenario(payload: dict[str, Any]) -> Scenario:
    turns = payload.get("turns") or {}
    turns_min = max(1, int(turns.get("min", payload.get("turns_min", 1))))
    turns_max = max(turns_min, int(turns.get("max", payload.get("turns_max", 1))))
    queries = tuple(str(query) for query in payload.get("queries", []))
    return Scenario(
        name=str(payload["name"]),
        weight=int(payload.get("weight", 1)),
        kind=str(payload.get("kind", "chat")),
        query_source=str(payload.get("query_source", "dataset")),
        turns_min=turns_min,
        turns_max=turns_max,
        queries=queries,
        kb_id=str(payload["kb_id"]) if payload.get("kb_id") else None,
    )


def load_perf_samples(dataset_path: Path) -> list[PerfSample]:
    eval_samples = load_samples(dataset_path)
    return [
        PerfSample(
            id=sample.id,
            query=sample.query,
            kb_id=str(sample.kb_id) if sample.kb_id else None,
            category=sample.category,
            must_refuse=sample.must_refuse,
        )
        for sample in eval_samples
    ]


def ensure_dataset_exists(dataset_path: Path) -> None:
    if not dataset_path.exists():
        raise FileNotFoundError(
            f"Performance dataset does not exist: {dataset_path}. "
            "Check profile.dataset.path."
        )


async def create_auth_headers(
    client: httpx.AsyncClient,
    *,
    auth: dict[str, Any],
) -> dict[str, str]:
    username = auth.get("username")
    password = str(auth.get("password") or "Password123")
    auto_register = bool(auth.get("auto_register", True))
    if not username:
        username = f"perf_user_{uuid.uuid4().hex[:12]}"

    if auto_register:
        register_response = await client.post(
            REGISTER_PATH,
            json={
                "username": username,
                "email": f"{username}@example.com",
                "password": password,
                "confirm_password": password,
            },
        )
        if not is_acceptable_register_response(register_response):
            register_response.raise_for_status()

    login_response = await client.post(
        LOGIN_PATH,
        data={"username": username, "password": password},
    )
    login_response.raise_for_status()
    token = login_response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def is_acceptable_register_response(response: httpx.Response) -> bool:
    if response.status_code in {200, 201}:
        return True
    if response.status_code == 409:
        return True
    if response.status_code != 422:
        return False
    try:
        body = response.json()
    except json.JSONDecodeError:
        return False
    code = str(body.get("code") or "")
    return code in REGISTER_CONFLICT_CODES


def choose_scenario(scenarios: tuple[Scenario, ...]) -> Scenario:
    weights = [max(0, scenario.weight) for scenario in scenarios]
    if not any(weights):
        raise ValueError("At least one scenario must have a positive weight")
    return random.choices(scenarios, weights=weights, k=1)[0]


def choose_sample(scenario: Scenario, samples: list[PerfSample]) -> PerfSample:
    if scenario.query_source == "inline" and scenario.queries:
        return PerfSample(
            id=f"inline-{uuid.uuid4().hex[:8]}",
            query=random.choice(scenario.queries),
            kb_id=scenario.kb_id,
            category=scenario.name,
            must_refuse=False,
        )
    sample = random.choice(samples)
    if scenario.kb_id:
        return PerfSample(
            id=sample.id,
            query=sample.query,
            kb_id=scenario.kb_id,
            category=sample.category,
            must_refuse=sample.must_refuse,
        )
    return sample


async def run_chat_turn(
    client: httpx.AsyncClient,
    *,
    headers: dict[str, str],
    scenario: Scenario,
    sample: PerfSample,
    session_id: str | None,
    request_group_id: str,
    turn_index: int,
) -> tuple[dict[str, Any], str | None]:
    payload: dict[str, Any] = {
        "query": sample.query,
        "client_request_id": (f"perf-{scenario.name}-{request_group_id}-{turn_index}"),
    }
    if sample.kb_id:
        payload["kb_id"] = sample.kb_id
    if session_id:
        payload["session_id"] = session_id

    started_at = time.perf_counter()
    status_code: int | None = None
    error_type: str | None = None
    error_message: str | None = None
    response_body: dict[str, Any] = {}
    try:
        response = await client.post(QUERY_SENT_PATH, headers=headers, json=payload)
        status_code = response.status_code
        response.raise_for_status()
        response_body = response.json()
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        error_type = f"http_{status_code}"
        error_message = str(exc)
    except Exception as exc:
        error_type = type(exc).__name__
        error_message = str(exc)

    latency_ms = int((time.perf_counter() - started_at) * 1000)
    answer_payload = response_body.get("answer") or {}
    answer_content = str(answer_payload.get("content") or "")
    search_context = answer_payload.get("search_context") or {}
    chunks = search_context.get("chunks") or []
    next_session_id = str(response_body.get("session_id") or session_id or "")
    return (
        {
            "request_group_id": request_group_id,
            "turn_index": turn_index,
            "scenario": scenario.name,
            "kind": scenario.kind,
            "sample_id": sample.id,
            "category": sample.category,
            "must_refuse": sample.must_refuse,
            "status_code": status_code,
            "success": error_message is None,
            "latency_ms": latency_ms,
            "retrieved_count": len(chunks),
            "answer_length": len(answer_content),
            "empty_answer": not answer_content.strip(),
            "error_type": error_type,
            "error_message": error_message,
        },
        next_session_id or None,
    )


async def run_health_check(
    client: httpx.AsyncClient,
    *,
    scenario: Scenario,
    request_group_id: str,
) -> dict[str, Any]:
    started_at = time.perf_counter()
    status_code: int | None = None
    error_type: str | None = None
    error_message: str | None = None
    try:
        response = await client.get(LIVE_PATH)
        status_code = response.status_code
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        error_type = f"http_{status_code}"
        error_message = str(exc)
    except Exception as exc:
        error_type = type(exc).__name__
        error_message = str(exc)
    latency_ms = int((time.perf_counter() - started_at) * 1000)
    return {
        "request_group_id": request_group_id,
        "turn_index": 1,
        "scenario": scenario.name,
        "kind": scenario.kind,
        "sample_id": None,
        "category": scenario.name,
        "must_refuse": False,
        "status_code": status_code,
        "success": error_message is None,
        "latency_ms": latency_ms,
        "retrieved_count": 0,
        "answer_length": 0,
        "empty_answer": False,
        "error_type": error_type,
        "error_message": error_message,
    }


async def run_scenario(
    client: httpx.AsyncClient,
    *,
    headers: dict[str, str],
    profile: Profile,
    samples: list[PerfSample],
    semaphore: asyncio.Semaphore,
) -> list[dict[str, Any]]:
    async with semaphore:
        scenario = choose_scenario(profile.scenarios)
        request_group_id = uuid.uuid4().hex[:10]
        if scenario.kind == "health":
            return [
                await run_health_check(
                    client,
                    scenario=scenario,
                    request_group_id=request_group_id,
                )
            ]

        session_id: str | None = None
        details: list[dict[str, Any]] = []
        turn_count = random.randint(scenario.turns_min, scenario.turns_max)
        for turn_index in range(1, turn_count + 1):
            sample = choose_sample(scenario, samples)
            detail, session_id = await run_chat_turn(
                client,
                headers=headers,
                scenario=scenario,
                sample=sample,
                session_id=session_id,
                request_group_id=request_group_id,
                turn_index=turn_index,
            )
            details.append(detail)
        return details


async def run_load(
    *,
    profile: Profile,
    base_url: str,
) -> dict[str, Any]:
    ensure_dataset_exists(profile.dataset_path)
    samples = load_perf_samples(profile.dataset_path)
    timeout = httpx.Timeout(profile.timeout_sec)
    semaphore = asyncio.Semaphore(profile.concurrency_limit)
    tasks: list[asyncio.Task[list[dict[str, Any]]]] = []
    started_at = time.perf_counter()

    async with httpx.AsyncClient(
        base_url=base_url,
        timeout=timeout,
        trust_env=False,
    ) as client:
        headers = await create_auth_headers(client, auth=profile.auth)
        interval_sec = 1.0 / profile.arrival_rate_rps
        stop_at = time.perf_counter() + profile.duration_sec
        next_arrival = time.perf_counter()
        while time.perf_counter() < stop_at:
            now = time.perf_counter()
            if now < next_arrival:
                await asyncio.sleep(next_arrival - now)
            task = asyncio.create_task(
                run_scenario(
                    client,
                    headers=headers,
                    profile=profile,
                    samples=samples,
                    semaphore=semaphore,
                )
            )
            tasks.append(task)
            next_arrival += interval_sec
        result_groups = await asyncio.gather(*tasks) if tasks else []

    runtime_sec = time.perf_counter() - started_at
    details = [detail for result_group in result_groups for detail in result_group]
    return build_report(
        profile=profile,
        base_url=base_url,
        runtime_sec=runtime_sec,
        details=details,
    )


def build_report(
    *,
    profile: Profile,
    base_url: str,
    runtime_sec: float,
    details: list[dict[str, Any]],
) -> dict[str, Any]:
    config = {
        "profile": str(profile.path),
        "profile_name": profile.name,
        "base_url": base_url,
        "duration_sec": profile.duration_sec,
        "arrival_rate_rps": profile.arrival_rate_rps,
        "concurrency_limit": profile.concurrency_limit,
        "timeout_sec": profile.timeout_sec,
        "dataset_path": str(profile.dataset_path),
        "percentile_method": "nearest_rank",
    }
    summary = summarize_details(details, runtime_sec=runtime_sec)
    return {
        "run": build_run_metadata(
            kind="perf_chat_api",
            dataset_path=profile.dataset_path,
            config=config,
        ),
        "summary": summary,
        "scenarios": summarize_by_scenario(details),
        "errors": summarize_errors(details),
        "details": details,
    }


def summarize_details(
    details: list[dict[str, Any]],
    *,
    runtime_sec: float | None,
    include_actual_rps: bool = True,
) -> dict[str, Any]:
    request_count = len(details)
    success_count = sum(1 for row in details if row["success"])
    failure_count = request_count - success_count
    latencies = [int(row["latency_ms"]) for row in details]
    answer_lengths = [int(row["answer_length"]) for row in details]
    retrieved_counts = [int(row["retrieved_count"]) for row in details]
    empty_answer_count = sum(1 for row in details if row["empty_answer"])
    summary: dict[str, Any] = {
        "requests": request_count,
        "success_count": success_count,
        "failure_count": failure_count,
        "error_rate": safe_div(failure_count, request_count),
        "p50_ms": percentile(latencies, 50),
        "p90_ms": percentile(latencies, 90),
        "p95_ms": percentile(latencies, 95),
        "p99_ms": percentile(latencies, 99),
        "max_ms": max(latencies, default=0),
        "avg_answer_length": safe_div(sum(answer_lengths), len(answer_lengths)),
        "avg_retrieved_count": safe_div(sum(retrieved_counts), len(retrieved_counts)),
        "empty_answer_rate": safe_div(empty_answer_count, request_count),
    }
    if runtime_sec is not None:
        summary["runtime_sec"] = round(runtime_sec, 3)
        if include_actual_rps:
            summary["actual_rps"] = safe_div(request_count, runtime_sec)
    return summary


def summarize_by_scenario(
    details: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in details:
        grouped[str(row["scenario"])].append(row)
    summaries: dict[str, dict[str, Any]] = {}
    for name, rows in sorted(grouped.items()):
        latency_sum_sec = sum_latency_sec(rows)
        summary = summarize_details(
            rows,
            runtime_sec=None,
            include_actual_rps=False,
        )
        summary["latency_sum_sec"] = round(latency_sum_sec, 3)
        summary["request_rate_estimate"] = safe_div(len(rows), latency_sum_sec)
        summaries[name] = summary
    return summaries


def sum_latency_sec(rows: list[dict[str, Any]]) -> float:
    return safe_div(sum(float(row["latency_ms"]) for row in rows), 1000.0)


def summarize_errors(details: list[dict[str, Any]]) -> dict[str, Any]:
    by_type = Counter(
        str(row["error_type"]) for row in details if row.get("error_type")
    )
    by_status = Counter(
        str(row["status_code"])
        for row in details
        if row.get("status_code") and not row.get("success")
    )
    return {
        "by_type": dict(sorted(by_type.items())),
        "by_status": dict(sorted(by_status.items())),
    }


def percentile(values: list[int], percentile_value: int) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(0, math.ceil((percentile_value / 100) * len(ordered)) - 1)
    return ordered[index]


async def async_main() -> None:
    args = parse_args()
    if args.seed is not None:
        random.seed(args.seed)
    profile = load_profile(args.profile)
    if profile.arrival_rate_rps <= 0:
        raise ValueError("arrival_rate_rps must be greater than 0")
    report = await run_load(profile=profile, base_url=args.base_url)
    write_eval_report(args.output, report)
    summary = report["summary"]
    created_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    print(
        f"[{created_at}] wrote {args.output} "
        f"requests={summary['requests']} "
        f"p95_ms={summary['p95_ms']} "
        f"error_rate={summary['error_rate']:.4f}"
    )


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
