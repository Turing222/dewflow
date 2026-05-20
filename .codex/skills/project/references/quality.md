# Quality Gates

Always prefix Python commands with `uv run`.

## Full Pipeline

```bash
make lint
make typecheck
make test
make check
```

## Focused Targets

```bash
make qa-lint
make qa-format
make qa-typecheck
make qa-boundaries
make qa-alembic-check
make qa-config-check
make qa-test-unit
make qa-test-integration
make qa-test-all
```

## Operational Constraints

- Do not modify code or files unless the user explicitly asks for implementation, code changes, or file edits.
- Keep generated write chunks under 150 lines per tool call.
- Cap noisy command output with `| head -200`.
- Do not browse localhost; use `curl` for health checks.
- Check Docker status with `docker compose ps`.
- Inspect Docker failures with `docker compose logs --tail=50 <svc>`.
