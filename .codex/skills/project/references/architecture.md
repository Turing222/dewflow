# Architecture Rules

## Web / Worker Split

- Web code in `backend.api`, `backend.services`, and `backend.middleware` depends on `contracts/interfaces.py`, not `backend.worker`.
- Worker code in `backend.worker` may depend on `services/` and `contracts/`, not `backend.api`.
- Web-to-worker communication goes through `AbstractTaskDispatcher`.
- Dispatch worker tasks through `task_dispatcher.enqueue_*()`, never `.kiq()` directly from web code.
- `scripts/check_import_boundaries.py` enforces this split.

## Dependency Injection

- `api/deps/` provides DI factories.
- Do not import worker tasks or worker modules in the web layer.
- Services receive dependencies through `__init__`, not global singletons.
- `AbstractUnitOfWork` wraps transactions and repositories.
- Repository methods receive `session` as an explicit parameter.

## 3-Tier Call Chain

```text
HTTP endpoint -> Service -> Repository -> ORM Model
```

- Endpoints own HTTP concerns only.
- Services own business logic.
- Repositories own SQLAlchemy queries.
- Do not query ORM models directly from endpoints.
