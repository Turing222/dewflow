# Edit Existing Reference

Use this reference when modifying existing files.

## Safety

- Inspect the current file before patching it.
- Treat uncommitted changes as user-owned unless you made them in the current turn.
- Do not revert unrelated changes.
- Use `apply_patch` for manual edits; reserve generators and formatters for intentional mechanical changes.

## Boundary Checks

- Web-facing code must not import `backend.worker`.
- Worker code must not import `backend.api`.
- Endpoints should handle HTTP concerns only.
- Services should own business logic.
- Repositories should own SQLAlchemy queries.
- Writes should happen inside the Unit of Work transaction boundary.
- Do not introduce bare `while True`; pagination, polling, retries, and scans must use bounded loops with explicit exit behavior.

## Validation Choice

- Style-only or skill/docs edits: run the relevant validator or inspect the diff.
- Service/repository behavior: run focused unit tests.
- API wiring or dependency overrides: run component tests.
- Import boundary risk: run `make qa-boundaries`.
