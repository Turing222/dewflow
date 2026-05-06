# CLAUDE.md — Dewflow Backend

## Project Overview

**Dewflow Backend** — Python 3.12, FastAPI async web server + TaskIQ worker.

- **Web**: FastAPI HTTP API at `backend/api/v1/`
- **Worker**: TaskIQ async tasks at `backend/worker/`
- **Database**: PostgreSQL + pgvector via SQLAlchemy async
- **Cache/Broker**: Redis (db=0 for app, db=1 for TaskIQ)
- **Observability**: OpenTelemetry → Langfuse
- **Storage**: Local filesystem or S3 (MinIO-compatible)

## Directory Map

```
backend/
  api/v1/endpoint/   - HTTP endpoints (auth, chat, knowledge, user, workspace, audit, permission)
  api/v1/api.py      - Router registration
  api/dependencies.py - FastAPI dependency injection
  api/deps/          - Dependency providers (services, uow factories)
  contracts/          - Abstract interfaces (AbstractUnitOfWork, AbstractLLMService, AbstractRAGService, AbstractTaskDispatcher)
  models/orm/         - SQLAlchemy ORM models (access, chat, chunk, knowledge, task, user)
  models/schemas/     - Pydantic DTOs (chat, knowledge, user, workspace, audit, permission, task)
  config/             - Pydantic-settings (web, worker, AI settings)
  services/           - Business logic (chat, knowledge, rag, chunking, user, workspace, audit, permission, task)
  repositories/       - Data access (access, chat, knowledge, task, user) — depends on AbstractUnitOfWork
  infra/              - Infrastructure (db session, redis, taskiq broker)
  middleware/         - FastAPI middleware
  worker/             - TaskIQ task implementations
  core/               - Exceptions, constants
  utils/              - Generic helpers
tests/                - unit/, integration/
scripts/              - Shell & Python automation scripts
configs/              - Deployment configs (Docker, Traefik, Prometheus, Langfuse)
alembic/              - Database migration chain
```

## Architecture Rules (CRITICAL)

### Web / Worker Dependency Split
- **Web** (`backend.api`, `backend.services`, `backend.middleware`) depends on `contracts/interfaces.py`, NOT on `worker/`
- **Worker** (`backend.worker/`) depends on `services/` and `contracts/`, NOT on `api/`
- All web→worker communication goes through `AbstractTaskDispatcher` interface
- Worker tasks are dispatched via `task_dispatcher.enqueue_*()` — never `.kiq()` directly
- `scripts/check_import_boundaries.py` enforces this split

### Dependency Injection
- `api/deps/` provides DI factories, NEVER import worker.tasks or worker modules in web layer
- Services receive dependencies via constructor (`__init__`), not global singletons
- Unit of Work pattern: `AbstractUnitOfWork` wraps transaction + all repositories
- Repository methods receive `session` as explicit parameter

### 3-Tier Call Chain
```
HTTP endpoint → Service → Repository → ORM Model
    ↑               ↑            ↑
  api/v1/       services/    repositories/
```
- Endpoints handle HTTP concerns only (status codes, request parsing)
- Services contain business logic
- Repositories contain SQLALchemy queries only
- Never query ORM models directly from endpoints

## Coding Conventions

### Naming
- Variables/functions: `snake_case`, Classes: `PascalCase`, Constants: `UPPER_SNAKE_CASE`
- Boolean prefix: `is_`, `has_`, `should_`, `can_`
- ALL identifiers in English
- Allowed abbreviations: `id`, `db`, `llm`, `rag`, `kb`, `s3`, `ip`, `url`, `api`, `http`, `jwt`, `otel`
- BANNED short names: `res`, `ret`, `tmp`, `obj`, `conn`, `rid` — use descriptive names instead

### Type Annotations
- HTTP endpoints: MUST annotate return type
- Dependency providers: MUST annotate return type
- Service/repository public methods: MUST annotate return type
- `__init__`: MUST annotate `-> None`
- Private helpers: annotate opportunistically when touched
- Don't introduce complex type aliases just for completeness

### Async / Sync
- Default to `def`; use `async def` only when `await` is needed
- Use `@staticmethod` when method doesn't access `self`
- Wrap sync blocking I/O in async context with `await asyncio.to_thread(...)`
- CPU-bound work → process pools or background tasks

### Comments
- Module header: 1 English sentence summary + Chinese explanation of responsibilities, boundaries, side effects
- Class/function docstrings: one sentence max if module header already covers it
- Inline comments: ONLY explain WHY and WHAT RISK — never explain WHAT the code does
- BANNED: `# 获取用户`, `# 执行查询`, `# 返回结果` — code is self-documenting
- Numbered step comments: only for algorithms, state machines, migrations, compensations

### Error Messages
- `message` field: user-visible, always in Chinese, never expose internals
- `error_code`: machine-readable, `UPPER_SNAKE_CASE` English
- `details`: structured info only, keys in `snake_case`, UUIDs stringified

## Quality Gates

Always use `uv run` for Python commands. Full validation pipeline:

```bash
make lint        # Ruff lint (qa-lint)
make typecheck   # Ty type checker (qa-typecheck)
make test        # All pytest suites (qa-test-all)
make check       # Combined lint + typecheck + tests (flow-static)
```

Individual gates:
```bash
make qa-lint              # Ruff lint only
make qa-format            # Ruff formatter
make qa-typecheck         # Ty type checker
make qa-boundaries        # Import boundary enforcement
make qa-alembic-check     # Migration chain integrity
make qa-config-check      # Config validation
make qa-test-unit         # Unit tests
make qa-test-integration  # Integration tests
make qa-test-all          # All tests except performance markers
```

## Operational Constraints

- **NEVER generate > 150 lines in a single tool call** — split writes if needed
- **Cap command output** with `| head -200` for git diff, logs, build output
- **No browser access** to localhost — use `curl` for health checks
- **Docker checks**: `docker compose ps` for status, `docker compose logs --tail=50 <svc>` for failures
- **uv commands**: always prefix with `uv run`

## Change Summary

After completing code changes, append a summary block at the end of the normal response:

```
## Change Summary
**What**: [one English sentence ≤ 30 words describing what was done]
**Why**: [key decision or trade-off]
**Affected**: [1-3 files/modules touched]
```

This is additive — normal response still comes first, summary serves as a compact handoff for downstream review by other AI tools.

## Commit Messages

Conventional commits, subject line in English:

```
type[(scope)]: English summary, ≤ 50 chars

Body (only for non-trivial changes):
- Why this approach
- Alternatives considered / risks
```

| type | when |
|------|------|
| `feat` | new feature |
| `fix` | bug fix |
| `refactor` | restructure without functional change |
| `chore` | deps, scripts, config |
| `docs` | documentation only |
| `test` | tests only |

Pre-commit checklist:
- **Referenced files**: If Makefile targets, imports, or `bash scripts/...` references were added, verify those files are staged — `git status` will show them as untracked if new
- **Scratch files**: Review untracked list for temporary test files, `.env` variants, or debug scripts — never `git add .`
- **Stage by name**: always `git add <specific files>`, not `git add -A`

Examples:
- `refactor(chat): offload non-stream generation to worker`
- `fix(knowledge): handle duplicate upload idempotency`
- `feat(rag): add contextual chunking with rerank`
