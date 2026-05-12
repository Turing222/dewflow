"""RAG 检索质量评测。

用法:
    # 普通 vector 检索
    python -m evals.eval_retrieval --dataset evals/dataset.sample.jsonl

    # hybrid 检索
    python -m evals.eval_retrieval --retrieval-mode hybrid

    # rerank 检索
    python -m evals.eval_retrieval --rerank --candidate-count 20 --rerank-top-k 4

    # 对比模式：同时跑 vector / hybrid / rerank 输出对比报告
    python -m evals.eval_retrieval --compare --output evals/reports/retrieval_compare.json

指标：
    hit_at_k, recall_at_k, mrr, avg_retrieved_count, avg_top_score, per_category
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

from backend.ai.providers.embedding.rag_embedding import RAGEmbedderFactory
from backend.config.ai_settings import ai_settings
from backend.config.llm import get_llm_model_config
from backend.infra.database import create_db_assets
from backend.services.rag_service import RAGService
from backend.services.unit_of_work import SQLAlchemyUnitOfWork
from backend.services.vector_index_service import VectorIndexService
from evals.common import (
    VALID_RETRIEVAL_MODES,
    ensure_parent_dir,
    load_samples,
    retrieve_chunks,
    safe_div,
    serialize_retrieved_chunks,
    summarize_by_category,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate RAG retrieval quality")
    parser.add_argument("--dataset", type=Path, required=True, help="Path to JSONL dataset")
    parser.add_argument(
        "--top-k",
        type=int,
        default=ai_settings.RAG_TOP_K,
        help="Top-K chunks to retrieve",
    )
    parser.add_argument(
        "--retrieval-mode",
        choices=sorted(VALID_RETRIEVAL_MODES),
        default="hybrid",
        help="Default retrieval mode when sample does not specify one",
    )
    parser.add_argument(
        "--rerank",
        action="store_true",
        help="Enable LLM rerank after candidate retrieval",
    )
    parser.add_argument(
        "--candidate-count",
        type=int,
        default=ai_settings.RAG_RERANK_CANDIDATE_COUNT,
        help="Candidate pool size for rerank",
    )
    parser.add_argument(
        "--rerank-top-k",
        type=int,
        default=ai_settings.RAG_RERANK_TOP_K,
        help="Top-K after rerank",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Run all retrieval modes and compare side-by-side",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("evals/reports/retrieval_report.json"),
        help="Output report path",
    )
    return parser.parse_args()


_RAW_METRIC_KEYS = (
    "hit_at_k",
    "recall_at_k",
    "mrr",
    "retrieved_count",
    "sample_latency_ms",
    "top_score",
)


async def _run_one_mode(
    *,
    samples: list,
    rag_service: RAGService,
    top_k: int,
    retrieval_mode: str,
    use_rerank: bool,
    candidate_count: int,
    rerank_top_k: int,
) -> tuple[list[dict], dict]:
    rows: list[dict] = []
    hit_total = 0.0
    recall_total = 0.0
    mrr_total = 0.0
    retrieved_count_total = 0.0
    top_score_total = 0.0
    error_count = 0

    for sample in samples:
        sample_mode = sample.retrieval_mode or retrieval_mode
        t0 = time.perf_counter()
        error_message: str | None = None

        try:
            chunks = await retrieve_chunks(
                rag_service=rag_service,
                query_text=sample.query,
                kb_id=sample.kb_id,
                top_k=top_k,
                retrieval_mode=sample_mode,
                use_rerank=use_rerank,
                candidate_count=candidate_count,
                rerank_top_k=rerank_top_k,
            )
        except Exception as exc:
            chunks = []
            error_message = str(exc)
            error_count += 1

        retrieved_ids = [chunk["id"] for chunk in chunks]
        hit_at_k = 0.0
        recall_at_k = 0.0
        mrr = 0.0

        if sample.expected_chunk_ids:
            expected = set(sample.expected_chunk_ids)
            found = [cid for cid in retrieved_ids if cid in expected]
            hit_at_k = 1.0 if found else 0.0
            recall_at_k = safe_div(len(set(found)), len(expected))
            first_rank = next(
                (idx + 1 for idx, cid in enumerate(retrieved_ids) if cid in expected),
                None,
            )
            mrr = safe_div(1.0, first_rank) if first_rank else 0.0
        elif sample.expected_keywords:
            context_text = "\n".join(chunk["content"] for chunk in chunks).lower()
            keyword_hits = sum(
                1 for kw in sample.expected_keywords if kw.lower() in context_text
            )
            hit_at_k = 1.0 if keyword_hits > 0 else 0.0
            recall_at_k = safe_div(keyword_hits, len(sample.expected_keywords))
            mrr = hit_at_k

        top_score = max(
            (float(chunk.get("score") or 0.0) for chunk in chunks), default=0.0
        )
        retrieved_count_total += len(chunks)
        top_score_total += top_score
        hit_total += hit_at_k
        recall_total += recall_at_k
        mrr_total += mrr

        rows.append(
            {
                "id": sample.id,
                "category": sample.category,
                "query": sample.query,
                "kb_id": str(sample.kb_id) if sample.kb_id else None,
                "retrieval_mode": sample_mode,
                "has_rerank": use_rerank,
                "must_refuse": sample.must_refuse,
                "retrieved_count": len(chunks),
                "sample_latency_ms": int((time.perf_counter() - t0) * 1000),
                "top_score": top_score,
                "hit_at_k": hit_at_k,
                "recall_at_k": recall_at_k,
                "mrr": mrr,
                "retrieved_chunk_ids": retrieved_ids,
                "retrieved_chunks": serialize_retrieved_chunks(chunks),
                "error_message": error_message,
            }
        )

    total = len(samples)
    summary = {
        "samples": total,
        "top_k": top_k,
        "retrieval_mode": retrieval_mode,
        "rerank": use_rerank,
        "error_count": error_count,
        "hit_at_k": safe_div(hit_total, total),
        "recall_at_k": safe_div(recall_total, total),
        "mrr": safe_div(mrr_total, total),
        "avg_retrieved_count": safe_div(retrieved_count_total, total),
        "avg_top_score": safe_div(top_score_total, total),
        "per_category": summarize_by_category(rows, list(_RAW_METRIC_KEYS)),
    }
    return rows, summary


async def run(args: argparse.Namespace) -> None:
    samples = load_samples(args.dataset)
    run_started_at = time.perf_counter()
    engine, session_factory = create_db_assets()
    try:
        uow = SQLAlchemyUnitOfWork(session_factory)
        embedding_profile = get_llm_model_config().resolve_embedding_profile(
            ai_settings.RAG_EMBED_PROVIDER
        )
        embedder = RAGEmbedderFactory.create(
            provider=embedding_profile.provider,
            model_name=embedding_profile.model,
            base_url=embedding_profile.resolve_base_url(),
            api_key=embedding_profile.resolve_api_key(),
            dimensions=embedding_profile.dimensions,
        )
        vector_index_service = VectorIndexService(uow=uow, embedder=embedder)

        if args.compare:
            # 对比模式：确保 rerank 需要 LLM service
            llm_service = None
            if ai_settings.RAG_RERANK_ENABLED:
                from backend.ai.providers.llm.factory import LLMProviderFactory
                llm_service = LLMProviderFactory.create()

            modes = [
                ("vector", False),
                ("hybrid", False),
                ("hybrid", True),
            ]
            comparison: dict[str, dict] = {}
            for mode, rerank in modes:
                label = f"{mode}_rerank" if rerank else mode
                rag_service = RAGService(
                    uow=uow,
                    embedder=embedder,
                    vector_index_service=vector_index_service,
                    top_k=args.top_k,
                    llm_service=llm_service,
                    rerank_candidate_count=args.candidate_count,
                    rerank_top_k=args.rerank_top_k,
                )
                _, summary = await _run_one_mode(
                    samples=samples,
                    rag_service=rag_service,
                    top_k=args.top_k,
                    retrieval_mode=mode,
                    use_rerank=rerank,
                    candidate_count=args.candidate_count,
                    rerank_top_k=args.rerank_top_k,
                )
                comparison[label] = summary
                print(f"\n--- {label} ---")
                print(json.dumps(summary, ensure_ascii=False, indent=2))

            report = {
                "dataset": str(args.dataset),
                "runtime_sec": round(time.perf_counter() - run_started_at, 3),
                "comparison": comparison,
            }
        else:
            rag_service = RAGService(
                uow=uow,
                embedder=embedder,
                vector_index_service=vector_index_service,
                top_k=args.top_k,
                rerank_candidate_count=args.candidate_count,
                rerank_top_k=args.rerank_top_k,
            )
            if args.rerank and ai_settings.RAG_RERANK_ENABLED:
                from backend.ai.providers.llm.factory import LLMProviderFactory
                rag_service.llm_service = LLMProviderFactory.create()

            details, summary = await _run_one_mode(
                samples=samples,
                rag_service=rag_service,
                top_k=args.top_k,
                retrieval_mode=args.retrieval_mode,
                use_rerank=args.rerank,
                candidate_count=args.candidate_count,
                rerank_top_k=args.rerank_top_k,
            )
            summary["runtime_sec"] = round(time.perf_counter() - run_started_at, 3)
            report = {"summary": summary, "details": details}

        ensure_parent_dir(args.output)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        print(f"\nReport saved to: {args.output}")
    finally:
        await engine.dispose()


def main() -> None:
    args = parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
