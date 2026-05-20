# Pytest Layering Reference

Use this reference when deciding where and how to add tests.

## Layer Selection

- Unit: pure logic, service rules, schema validation, repository query construction with fake or mocked sessions.
- Component: FastAPI routing, dependency overrides, middleware, request parsing, response serialization, or exception-to-HTTP mapping.
- Integration: real PostgreSQL, Redis, S3, TaskIQ broker, migrations, or real external providers.
- Smoke: running environment checks through real HTTP.

Prefer the lowest layer that proves the behavior.

## Placement

- Services: `tests/unit/services/`
- Repositories: `tests/unit/repositories/`
- API handler logic: `tests/unit/api/`
- API wiring or ASGI behavior: `tests/component/api/`
- Worker logic without a real broker: `tests/unit/worker/`
- Config parsing: `tests/unit/config/`
- Real external dependencies: `tests/integration/`
- Manual exploratory requests: `tests/manual/`

## Markers

- No marker for pure unit tests.
- `pytest.mark.component` for component tests.
- `pytest.mark.integration` plus `requires_db`, `requires_redis`, `requires_taskiq`, `requires_s3`, or `requires_llm` when a real resource is used.
- `pytest.mark.smoke` for running-environment HTTP checks.

## Verification

Use focused commands first:

```bash
uv run pytest tests/unit/path/to/test_file.py
uv run pytest tests/component/path/to/test_file.py
make qa-test-unit
```
