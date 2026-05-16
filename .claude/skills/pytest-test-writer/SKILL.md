---
name: pytest-test-writer
description: Use when working in this Python/FastAPI backend repository and the user asks to create or update pytest tests, add backend test coverage, or add tests for backend code changes. Follow repository test conventions, choose the proper unit/component/integration/smoke layer, fixtures, markers, and verification commands. Do not use for frontend, Jest, Playwright, Go, Java, or non-pytest tests unless the user explicitly asks to adapt the guidance.
---

# Pytest Test Writer

Create or extend pytest tests for this Python/FastAPI backend repository.

The goal is to add the **smallest sufficient test coverage** for the behavior that changed, while matching the repository's existing conventions.

Repository convention files are the source of truth. If this skill conflicts with any of the following files, follow the repository files instead:

- `tests/CONVENTIONS.md`
- `tests/README.md`
- `pyproject.toml`
- `pytest.ini`
- `tox.ini`
- relevant `conftest.py` files
- nearby existing tests for the same layer or feature

## Step 1: Analyze the Change

Before writing or editing tests, determine:

1. **What changed?** — Read the diff, issue, user request, or specified module to understand the modified behavior.
2. **What layer was touched?** — endpoint / schema / service / repository / worker / infra / middleware / AI / config.
3. **How significant is the change?** — Use the layer selection matrix below to decide which test layers are required.
4. **What existing tests cover similar behavior?** — Search nearby test files and mirror existing fixture, factory, marker, naming, and assertion style.
5. **What test configuration exists?** — Read available pytest config and marker definitions before adding new markers or assuming marker names.
6. **What external resources are real?** — Distinguish real DB/Redis/S3/TaskIQ/LLM usage from fake, mock, stub, or test-value strings.

If the changed behavior is already covered by existing tests, prefer extending the existing test file instead of creating a new file.

## Step 2: Select Test Layer(s)

### Layer Selection Matrix

| Change scope | Unit | Component | Integration | Smoke |
|---|---:|---:|---:|---:|
| Pure logic, no external dependencies | **required** | — | — | — |
| Pydantic/schema/request/response model change | **required** | recommended if FastAPI serialization matters | — | — |
| New or changed endpoint handler | **required** | recommended | — | — |
| Router registration / dependency override wiring | — | **required** | — | — |
| Auth / permission / dependency override change | **required** | **required** | optional | — |
| Middleware / exception handler / HTTP infra | — | **required** | — | — |
| Error mapping / exception-to-HTTP response change | — | **required** | — | — |
| Service business rule change | **required** | — | — | — |
| Repository query construction change | **required** with mock/fake session | — | if query correctness depends on real DB behavior | — |
| Data serialization / pagination / filtering behavior | **required** | recommended | if DB-specific query behavior matters | — |
| Cross-service orchestration / workflow | **required** | optional | if end-to-end collaboration is required | — |
| New or changed worker task logic | **required** | — | if broker-backed execution matters | — |
| Settings / env / config parsing change | **required** | optional | if runtime/deployment behavior matters | if deployed |
| New DB migration or schema change | — | — | **required** | — |
| New real external integration: S3, LLM, Redis, broker, external API | — | — | **required** | optional if deployed |
| Full user-facing feature across multiple layers | **required** | **required** | recommended | if deployed |
| Production deployment / runtime config change | — | — | optional | **required** |

### Decision Rules

- **Unit tests are the baseline.** Every non-trivial code change gets at least one unit test unless existing tests already cover the changed behavior.
- **Component tests** are needed when the behavior depends on FastAPI wiring, router registration, dependency override, middleware chaining, request parsing, response serialization, or exception-to-HTTP mapping.
- **Integration tests** are needed only when correctness depends on a real external dependency, actual PostgreSQL behavior, DB migration behavior, Redis behavior, real S3-compatible storage, real TaskIQ broker/worker collaboration, or a real LLM/API provider.
- **Smoke tests** are only for deployed or running environments and should verify critical HTTP paths are reachable. They should not duplicate detailed unit/component assertions.
- Prefer the **lowest layer that proves the behavior**. Do not add integration tests when a unit or component test fully verifies the change.

## Step 3: Place the Test File

Follow repository placement rules. If no stronger local convention exists, use:

| Test subject | Directory |
|---|---|
| API endpoint direct call as plain function/unit | `tests/unit/api/` |
| FastAPI router / ASGI client / dependency override / fake service | `tests/component/api/` |
| Middleware / exception handler / HTTP infra | `tests/component/http/` |
| Service business rule | `tests/unit/services/` |
| Repository query construction with mock/fake session | `tests/unit/repositories/` |
| Workflow / orchestrator / cross-service coordination | `tests/unit/workflows/` |
| Redis / TaskIQ / storage / DB session infrastructure wrappers | `tests/unit/infra/` |
| AI / RAG / prompt / token / embedding logic | `tests/unit/ai/` |
| Worker task logic without real broker | `tests/unit/worker/` |
| Config parsing / settings validation | `tests/unit/config/` |
| Core exceptions / security / constants | `tests/unit/core/` |
| ORM or Pydantic model behavior | `tests/unit/models/` or `tests/unit/schemas/` |
| Isolated middleware logic without ASGI collaboration | `tests/unit/middleware/` |
| Generic helpers and pure utilities | `tests/unit/utils/` |
| Real DB / Redis / S3 / broker / external provider collaboration | `tests/integration/` |
| Real HTTP stack against running environment | `tests/smoke/` |
| Concurrency, load, timing, benchmark, or resource-sensitive behavior | `tests/performance/` |
| Manual diagnostics or exploratory verification material | `tests/manual/` |

**Naming:** use `test_<module_or_behavior>.py`.

Because the directory already expresses the test layer, do **not** append `_unit`, `_component`, or `_integration` to the filename unless the repository already uses that pattern nearby.

## Step 4: Apply Markers

Use markers only when they communicate how the test should be selected or what real resource it requires.

| Marker | When to use |
|---|---|
| *(none)* | Pure unit test; default |
| `component` | Component test using ASGI client, dependency override, fake service, middleware chain, or HTTP serialization |
| `integration` | Test depends on real PostgreSQL, Redis, S3, TaskIQ broker/worker, LLM provider, or full app lifecycle |
| `smoke` | Test accesses a running environment via real HTTP |
| `performance` | Concurrency, load, timing, benchmark, or performance-sensitive test; usually excluded by default |
| `requires_db` | Test uses a real DB engine/session, migration, transaction, or PostgreSQL-specific behavior |
| `requires_redis` | Test connects to a real Redis server/client |
| `requires_taskiq` | Test starts/connects to a real TaskIQ broker, worker, or broker-backed task execution |
| `requires_s3` | Test uses a real S3-compatible client or endpoint |
| `requires_llm` | Test calls a real LLM/embedding provider or requires a real provider API key |
| `local_only` | Test only runs under `DEWFLOW_TEST_PROFILE=local` |
| `ci_only` | Test only runs under `DEWFLOW_TEST_PROFILE=ci` |

### Marker Syntax

Use file-level `pytestmark` when all tests in the file share the same marker.

```python
import pytest

pytestmark = pytest.mark.component
```

Use a list for multiple file-level markers.

```python
import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.requires_db,
]
```

Use function-level markers only when one test in the file has different requirements.

```python
import pytest


@pytest.mark.requires_db
async def test_repository_persists_status_change(db_session) -> None:
    ...
```

### Resource Marker Rules

Fake, mock, stub, in-memory, or test-value usage does **not** need `requires_*` markers.

Examples that do **not** require resource markers:

- `api_key="test-key"`
- `s3://bucket/key` as a plain string
- `FakeRedis`
- `StubLLMService`
- mocked `.kiq(...)`
- fake repository/session object
- monkeypatched provider client

Add `requires_*` markers only when the test actually connects to or depends on a real external resource.

Repository marker audit checks obvious real-dependency signatures. Add matching markers when a test file contains:

| Signature | Required marker |
|---|---|
| `create_async_engine(...)` | `requires_db` |
| `redis.from_url(...)` | `requires_redis` |
| `.kiq(...)` or `taskiq worker` | `requires_taskiq` |
| real S3 client or `TEST_S3_ENDPOINT_URL` | `requires_s3` |
| `TEST_LLM_API_KEY` | `requires_llm` |

`tests/smoke/` uses `SMOKE_*` environment variables and the `smoke` marker. It does not need `requires_*` markers unless repository conventions later require them.

## Step 5: Write the Test

### Default File Structure: Sync Test

Use sync tests by default when the test body does not need `await`.

```python
"""<One-line English summary>.

职责：<中文说明测试职责>；边界：<中文说明不覆盖的外部边界>；副作用：<中文说明副作用，通常为无>。
"""


def test_<behavior>_<expected_result>(...) -> None:
    ...
```

### Async File Structure

Use async tests only when the test body contains `await`.

```python
"""<One-line English summary>.

职责：<中文说明测试职责>；边界：<中文说明不覆盖的外部边界>；副作用：<中文说明副作用，通常为无>。
"""

import pytest

pytestmark = pytest.mark.asyncio


async def test_<behavior>_<expected_result>(...) -> None:
    ...
```

### Async Fixture Structure

Use async fixtures only when fixture setup or teardown requires `await`.

```python
from collections.abc import AsyncIterator

import pytest_asyncio


@pytest_asyncio.fixture
async def <descriptive_fixture_name>() -> AsyncIterator[<ReturnType>]:
    resource = await create_resource()
    try:
        yield resource
    finally:
        await resource.aclose()
```

If the repository already uses `pytest.fixture` for async fixtures and it works with the configured pytest plugins, follow the repository convention.

### Naming Convention

Use descriptive names that state the behavior and expected result.

Good:

```python
def test_create_user_returns_400_when_service_returns_none() -> None:
    ...
```

Bad:

```python
def test_success() -> None:
    ...

def test_error() -> None:
    ...
```

Fixture names should describe capability or context:

- `fake_user_repo`
- `mock_task_dispatcher`
- `payload_client`
- `frozen_clock`
- `authorized_client`

Fake/mock/stub classes should use clear prefixes:

- `FakeRedis`
- `MockTaskDispatcher`
- `StubLLMService`

### Assertion Style

Assert externally meaningful behavior first:

- status codes
- response body fields
- returned domain values
- raised exception type
- persisted state
- emitted event/task where relevant

Assert mock call arguments only for critical collaboration parameters. Do not over-pin call order, private implementation details, or incidental values.

For error messages, assert stable fragments instead of full stack traces or internal text.

Prefer small, complete test data. Move complex payloads into local fixtures, builders, or helper functions.

### Behavior Boundary Coverage

For each changed module, consider:

1. **Success path** — expected valid behavior.
2. **Rejection / failure path** — invalid input, permission denied, service error, not found.
3. **Boundary values** — empty, zero, max, off-by-one, missing optional field.
4. **Skip / bypass path** — conditional logic that short-circuits.
5. **Dependency exception path** — downstream raises, returns `None`, returns empty result, times out, or rejects.

Not every file needs all five categories. Omit obvious non-applicable categories silently. Add a short comment only when the omission is non-obvious or prevents future over-testing.

### Fixture Rules

- Keep fixtures local by default.
- Promote a fixture to a shared `conftest.py` only when reused by at least two test files.
- `tests/conftest.py` must stay lightweight: no app startup, no `backend.main` import, and no external connections.
- Subdirectory `conftest.py` may contain layer-specific fixtures such as app lifespan, ASGI client, DB/Redis fixtures, or dependency overrides.
- Pin nondeterministic sources: env vars, time, UUIDs, random values, token counts, and generated IDs.
- Prefer builders/factories over large inline payloads when the object has many fields.

### Async Rules

- Use `async def` and `pytest.mark.asyncio` only when the test body contains `await`.
- Do not put sync blocking I/O directly inside async tests. Use the code's async wrapper or `await asyncio.to_thread(...)`.
- Prefer file-level `pytestmark = pytest.mark.asyncio` only when all tests in the file are async.
- Do not make fixtures async unless setup or teardown needs `await`.

### Module Header

Every test file starts with a module header:

```python
"""<English summary>.

职责：<中文说明测试职责>；边界：<中文说明不覆盖的外部边界>；副作用：<中文说明副作用，通常为无>。
"""
```

Keep the header factual. Do not write long narrative comments in the test body.

## Step 6: Verify

After creating or modifying tests, run the narrowest useful checks first.

```bash
# Targeted collection check for the new or modified file
uv run pytest --collect-only tests/<layer>/<dir>/test_<name>.py

# Run the new or modified test file
uv run pytest tests/<layer>/<dir>/test_<name>.py -v
```

Prefer repository Makefile targets for broader verification:

```bash
make qa-test-unit
make qa-test-component
make qa-test-integration
make qa-test-markers
```

Choose the smallest Makefile target that matches the touched layer. For full default pytest coverage, use:

```bash
make qa-test-all
```

When changing shared behavior, run the nearest affected test group:

```bash
uv run pytest tests/unit/<area> -v
uv run pytest tests/component/<area> -v
```

When changing marker usage, directories, or integration tests, include:

```bash
make qa-test-markers
uv run pytest --collect-only tests/integration
```

For integration or smoke tests, do not assume required services are available. Check repository documentation and environment variables first.

## Quick Reference: Change Severity → Test Scope

```text
Tiny      typo, import cleanup, constant rename already covered     → no new test if existing coverage is enough
Small     bug fix or single method behavior change                  → unit test
Medium    new endpoint, schema behavior, service method, wiring      → unit + component when wiring/serialization matters
Large     feature across API/service/repository/worker               → unit + component + selective integration
Critical  real external dependency, migration, deployment config      → integration + smoke if deployed
```

## Hard Rules

- Always inspect nearby existing tests before creating a new style or helper.
- Always follow repository convention files when they conflict with this skill.
- Every non-trivial backend code change needs at least one relevant test unless existing tests already cover it.
- Do not write integration or smoke tests for behavior that can be fully verified with unit/component tests.
- Preserve the web/worker import boundary: web/API/service tests must not import `backend.worker`.
- Verify worker dispatch through `AbstractTaskDispatcher` fakes/mocks and `enqueue_*()` calls; do not call `.kiq()` directly outside real TaskIQ integration tests.
- Worker tests may import `backend.worker`, but must not import `backend.api` unless the repository convention for that specific test says otherwise.
- Do not import `backend.main` or create a FastAPI app in top-level `tests/conftest.py`.
- Do not access real PostgreSQL, Redis, S3, TaskIQ, LLM providers, or external APIs in unit tests.
- Do not use `smoke` marker in `tests/unit/`; use names like `construction`, `minimal`, or `loads_default_config` instead.
- Do not add `requires_*` markers for fake/mock/stub objects or test-value strings.
- Do not modify production code just to make a test easier unless the user asked for implementation changes or the existing production code is clearly broken.
- If production code must change to make the test meaningful, explain the production-code issue separately.
- Do not write narrative comments such as `# 创建用户` or `# 验证结果`. Comments should explain only why a non-obvious choice exists, what risk is being guarded against, or what external constraint applies.
