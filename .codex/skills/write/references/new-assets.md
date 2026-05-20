# New Asset Reference

Use this reference when adding new files or a new capability.

## Placement

- API routes live under `backend/api/v1/endpoint/` and route registration belongs in `backend/api/v1/api.py`.
- Business rules live in `backend/services/`.
- Data access lives in `backend/repositories/` and receives `session` explicitly.
- Contracts live in `backend/contracts/` when web and worker need a shared interface.
- Worker tasks live in `backend/worker/`; web code dispatches only through `AbstractTaskDispatcher`.
- Local Codex skills live under `.codex/skills/<skill-name>/`.

## Creation Rules

- Prefer a nearby file as the template for imports, module header style, naming, and test placement.
- Keep new abstractions small until at least two real call sites need them.
- Do not introduce scripts, generated workflows, or automation scaffolding unless requested.
- For Python code, include public return types and `__init__ -> None`.

## Validation

Choose the narrowest useful check:

- Local skill changes: run the skill validator.
- Python source changes: run `make qa-lint` or the focused test command.
- Boundary-sensitive changes: run `make qa-boundaries`.
