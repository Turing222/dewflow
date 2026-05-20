# Coding Conventions

## Naming

- Variables/functions: `snake_case`
- Classes: `PascalCase`
- Constants: `UPPER_SNAKE_CASE`
- Boolean prefix: `is_`, `has_`, `should_`, `can_`
- All identifiers in English
- Allowed abbreviations: `id`, `db`, `llm`, `rag`, `kb`, `s3`, `ip`, `url`, `api`, `http`, `jwt`, `otel`
- Banned short names: `res`, `ret`, `tmp`, `obj`, `conn`, `rid`

## Type Annotations

- HTTP endpoints must annotate return type.
- Dependency providers must annotate return type.
- Service and repository public methods must annotate return type.
- `__init__` must annotate `-> None`.
- Private helpers should be annotated opportunistically when touched.
- Do not introduce complex type aliases just for completeness.

## Async / Sync

- Default to `def`; use `async def` only when `await` is needed.
- Use `@staticmethod` when a method does not access `self`.
- Wrap sync blocking I/O in async context with `await asyncio.to_thread(...)`.
- Use process pools or background tasks for CPU-bound work.

## Comments And Errors

- Module header: one English sentence summary plus Chinese responsibilities, boundaries, and side effects.
- Class/function docstrings: one sentence max if the module header already covers responsibilities.
- Inline comments explain why or risk only.
- User-visible `message` fields are Chinese and never expose internals.
- `error_code` is `UPPER_SNAKE_CASE` English.
- `details` keys are `snake_case`; stringify UUIDs.
