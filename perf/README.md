# Dewflow Perf

`perf/` stores repeatable performance load tooling. It is separate from
`evals/`: performance runs measure latency, throughput, errors, and lightweight
behavior signals; Ragas and LLM-as-judge quality scoring stay in `evals/`.

## Chat API Load Runner

```bash
uv run python -m perf.chat_api_load \
  --profile perf/profiles/enterprise_smoke.json \
  --base-url http://localhost:8000 \
  --output perf/reports/chat_api_load_report.json \
  --seed 42
```

The default Make target uses the same runner:

```bash
make qa-perf-chat
```

## Profiles

Profiles are JSON files under `perf/profiles/` and define:

| Field | Meaning |
| --- | --- |
| `duration_sec` | How long to schedule new scenario arrivals. |
| `arrival_rate_rps` | Target scenario arrivals per second. |
| `concurrency_limit` | Maximum in-flight scenario tasks. |
| `timeout_sec` | HTTP timeout per request. |
| `dataset.path` | JSONL dataset used for query samples. |
| `auth` | Temporary or stable load-test user credentials. |
| `scenarios` | Weighted traffic model. |

Built-in profiles:

- `enterprise_smoke.json`: short, cheap validation profile.
- `steady.json`: longer steady-state profile.
- `spike.json`: higher-arrival-rate spike profile with lower health-check weight
  so most arrivals hit chat paths.

## Report

Reports are written to `perf/reports/`, which is ignored by git. The JSON report
contains:

- `run`: profile, dataset, git commit, and run metadata.
- `summary`: total requests, successes, failures, actual RPS, p50/p90/p95/p99,
  max latency, error rate, average answer length, average retrieved count, and
  empty answer rate.
- `scenarios`: the same summary grouped by scenario. Scenario-level
  `request_rate_estimate` uses summed request latency as the denominator, so it
  is useful for comparison but is not wall-clock RPS under concurrency.
- `errors`: failures grouped by HTTP status or exception type.
- `details`: per-request rows for local diagnosis.

Latency percentiles use nearest-rank selection to keep the JSON report easy to
compare with common monitoring dashboards.

## Locust

`tests/performance/locustfile.py` is still available for exploratory/manual load
testing:

```bash
make qa-perf-chat-locust
```

Use the `perf` runner for baseline reports and candidate comparisons. Use
Locust when you want interactive exploration or its web UI.
