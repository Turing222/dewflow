---
name: edit
description: Modify existing Dewflow backend files safely. Use when the user asks to change, fix, update, refactor, rename, remove, or adjust existing code, docs, config, scripts, migrations, or local skills; use add-tests for test-only changes.
---

# Edit

Use this skill when the primary task is changing existing files.

## Core Flow

1. Read the target files and nearby tests before editing.
2. Check `git status --short` so user changes are not overwritten.
3. Apply the smallest coherent patch that satisfies the latest request.
4. Preserve architecture boundaries: endpoint → service → repository, and web → dispatcher → worker.
5. Do not add bare `while True`; use an explicit bounded loop with a clear exit path.
6. Run focused validation first, then broader checks only when the change risk justifies it.
7. If behavior changed or coverage gaps are exposed, consider loading `add-tests`.
8. If files were modified, append the Change Summary block from `.codex/skills/project/references/handoff.md`.

## Progressive Disclosure

- Read [references/edit-existing.md](references/edit-existing.md) for edit safety, boundary checks, and validation selection.
