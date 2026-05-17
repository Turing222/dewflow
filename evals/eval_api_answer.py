"""RAG API answer quality evaluation.

职责：通过真实 HTTP API 采样回答并生成 Ragas 评测报告。
边界：只作为 L3 评测入口运行，不参与 pytest 默认测试集。
说明：evals 不导入 tests/smoke helper，避免评测入口依赖 pytest fixture 与测试包。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from evals.common import (
    build_ragas_samples,
    ensure_parent_dir,
    load_samples,
    safe_div,
    summarize_by_category,
)
from evals.eval_answer import _create_eval_llm, _has_ragas

REGISTER_PATH = "/api/v1/auth/register"
LOGIN_PATH = "/api/v1/auth/login"
QUERY_SENT_PATH = "/api/v1/chat/query_sent"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate RAG answers through HTTP API")
    parser.add_argument("--dataset", type=Path, required=True, help="Path to JSONL dataset")
    parser.add_argument(
        "--base-url",
        default=os.getenv("SMOKE_BASE_URL", "http://localhost:8000"),
        help="Smoke API base URL",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("evals/reports/api_answer_report.json"),
        help="Output report path",
    )
    parser.add_argument("--timeout", type=float, default=60.0, help="HTTP timeout seconds")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=4,
        help="Maximum concurrent API answer requests",
    )
    return parser.parse_args()


async def create_eval_headers(client: httpx.AsyncClient) -> dict[str, str]:
    suffix = uuid.uuid4().hex[:12]
    username = f"api_eval_{suffix}"
    password = "Password123"
    register_response = await client.post(
        REGISTER_PATH,
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": password,
            "confirm_password": password,
        },
    )
    register_response.raise_for_status()

    login_response = await client.post(
        LOGIN_PATH,
        data={"username": username, "password": password},
    )
    login_response.raise_for_status()
    token = login_response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def query_api_answer(
    client: httpx.AsyncClient,
    *,
    headers: dict[str, str],
    sample: Any,
) -> tuple[str, dict[str, Any], int]:
    payload: dict[str, Any] = {
        "query": sample.query,
        "client_request_id": f"api-eval-{sample.id}-{uuid.uuid4().hex[:8]}",
    }
    if sample.kb_id:
        payload["kb_id"] = str(sample.kb_id)

    started_at = time.perf_counter()
    response = await client.post(QUERY_SENT_PATH, headers=headers, json=payload)
    latency_ms = int((time.perf_counter() - started_at) * 1000)
    response.raise_for_status()

    body = response.json()
    answer_payload = body.get("answer") or {}
    answer = str(answer_payload.get("content") or "")
    return answer, body, latency_ms


def context_texts(api_body: dict[str, Any]) -> list[str]:
    answer_payload = api_body.get("answer") or {}
    search_context = answer_payload.get("search_context") or {}
    chunks = search_context.get("chunks") or []
    return [str(chunk.get("content") or "") for chunk in chunks]


async def run_ragas(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows or not _has_ragas():
        return {}

    from ragas import EvaluationDataset, evaluate
    from ragas.metrics.collections import (
        AnswerCorrectness,
        AnswerRelevancy,
        Faithfulness,
    )

    ragas_rows = [
        row for row in rows if row["answer"].strip() and row["retrieved_contexts"]
    ]
    if not ragas_rows:
        return {}

    metrics = [Faithfulness(), AnswerRelevancy()]
    if any(row.get("reference_answer") for row in ragas_rows):
        metrics.append(AnswerCorrectness())

    eval_llm, _eval_model = _create_eval_llm()
    result = evaluate(
        dataset=EvaluationDataset(samples=build_ragas_samples(ragas_rows)),
        metrics=metrics,
        llm=eval_llm,
    )
    frame = result.to_pandas()
    return {
        col: float(frame[col].mean())
        for col in frame.columns
        if col not in ("user_input", "retrieved_contexts", "response", "reference")
    }


async def run(args: argparse.Namespace) -> None:
    samples = load_samples(args.dataset)
    run_started_at = time.perf_counter()
    concurrency = max(1, args.concurrency)
    semaphore = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient(
        base_url=args.base_url,
        timeout=args.timeout,
        trust_env=False,
    ) as client:
        headers = await create_eval_headers(client)

        async def evaluate_sample(sample: Any) -> dict[str, Any]:
            error_message: str | None = None
            answer = ""
            api_body: dict[str, Any] = {}
            latency_ms = 0
            async with semaphore:
                try:
                    answer, api_body, latency_ms = await query_api_answer(
                        client,
                        headers=headers,
                        sample=sample,
                    )
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code == 401:
                        refreshed_headers = await create_eval_headers(client)
                        try:
                            answer, api_body, latency_ms = await query_api_answer(
                                client,
                                headers=refreshed_headers,
                                sample=sample,
                            )
                        except Exception as retry_exc:
                            error_message = str(retry_exc)
                    else:
                        error_message = str(exc)
                except Exception as exc:
                    error_message = str(exc)

            contexts = context_texts(api_body)
            return {
                "id": sample.id,
                "category": sample.category,
                "query": sample.query,
                "kb_id": str(sample.kb_id) if sample.kb_id else None,
                "must_refuse": sample.must_refuse,
                "answer": answer,
                "reference_answer": sample.reference_answer,
                "retrieved_contexts": contexts,
                "retrieved_count": len(contexts),
                "total_latency_ms": latency_ms,
                "error_message": error_message,
            }

        rows = await asyncio.gather(*(evaluate_sample(sample) for sample in samples))

    latency_total = sum(float(row["total_latency_ms"]) for row in rows)
    error_count = sum(1 for row in rows if row["error_message"])
    ragas_scores = await run_ragas(rows)
    summary = {
        "samples": len(samples),
        "base_url": args.base_url,
        "error_count": error_count,
        "avg_total_latency_ms": safe_div(latency_total, len(samples)),
        "runtime_sec": round(time.perf_counter() - run_started_at, 3),
        "ragas_scores": ragas_scores,
        "per_category": summarize_by_category(
            rows,
            ["total_latency_ms", "retrieved_count"],
        ),
    }
    ensure_parent_dir(args.output)
    args.output.write_text(
        json.dumps({"summary": summary, "details": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("\nAPI Answer Eval Done")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Report saved to: {args.output}")


def main() -> None:
    asyncio.run(run(parse_args()))


if __name__ == "__main__":
    main()
