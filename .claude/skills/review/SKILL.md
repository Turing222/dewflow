---
name: review
description: Multi-angle code review against project conventions. Covers architecture, logic, naming, and style as separate passes with different context depths. Triggers on: review, code review, review my code, check this, pre-commit check, /review.
---

# Code Review

Review staged or specified changes against project conventions defined in CLAUDE.md.

## Review Strategy

Run reviews by dimension, from shallowest to deepest context. Shallower dimensions can run in parallel.

### Pass 1: Style & Naming (shallow — diff only)

Read the diff. Do NOT expand references or trace call chains.

Check against CLAUDE.md conventions:

- **Naming**: banned short names (`res`, `ret`, `tmp`, `obj`, `conn`, `rid`), boolean prefix (`is_`, `has_`, `should_`, `can_`), allowed abbreviations
- **Type annotations**: public methods, endpoints, `__init__ -> None` all annotated
- **Comments**: module header format, inline comments only explain WHY/WHAT RISK, no narrative comments (`# 获取用户`, `# execute query`)
- **Error messages**: `message` in Chinese, `error_code` in UPPER_SNAKE_CASE English

### Pass 2: Architecture (medium — diff + contracts)

Read the diff + `backend/contracts/interfaces.py` + directory structure.

Check:

- Web layer (`api/`, `services/`) does NOT import from `worker/`
- Worker communication goes through `AbstractTaskDispatcher`, never `.kiq()` directly
- Dependencies injected via constructor, not global singletons
- New code follows 3-tier chain: endpoint → service → repository (no ORM queries in endpoints)
- New files placed in the correct directory per the directory map

### Pass 3: Logic & Correctness (deep — expand references as needed)

Read the diff. For each changed function, identify its callers and callees. Expand references when something looks suspicious.

Check:

- **None guards**: repository/service methods returning `T | None` are guarded before attribute access
- **Async correctness**: sync blocking I/O wrapped in `await asyncio.to_thread()`, no `async def` without `await`
- **Transaction boundary**: writes are within UoW commit scope, rollback on failure
- **Error handling**: exceptions caught at the right layer, no bare `except: pass`
- **Resource cleanup**: file handles, Redis connections, DB sessions properly closed
- **Idempotency**: duplicate requests handled safely (check for `idempotency_lock_key` patterns)

## Output Format

Group findings by pass. Each finding includes file:line, severity, and a one-line fix.

```
## Review: [branch or files]

### Style & Naming
| Severity | File:Line | Issue | Fix |
|----------|-----------|-------|-----|

### Architecture
| Severity | File:Line | Issue | Fix |
|----------|-----------|-------|-----|

### Logic & Correctness
| Severity | File:Line | Issue | Fix |
|----------|-----------|-------|-----|
```

Severity labels:

| Label | Meaning |
|-------|---------|
| `Must Fix` | violates a CRITICAL rule, would cause bugs |
| `Should Fix` | violates a convention, degrades maintainability |
| `Note` | observation, optional improvement |

## Rules

- Only report actual problems.
- When a pass has **no findings**: write `No issues found.` only. Do NOT list verified items or "all changes align" commentary — a clean pass speaks for itself.
- When a pass has **findings**: use the table format. One row per finding.
- Do NOT re-state CLAUDE.md rules in findings — reference them by name (e.g. "violates naming: banned short name `res`")
- When a finding spans multiple lines, reference the first line
- Architecture violations are always `Must Fix`
- Never combine unrelated issues into one finding
