---
name: write
description: Create new repository assets for Dewflow backend. Use when the user asks to add or create new backend code, docs, config, migrations, scripts, local skills, or other files; use add-tests for test-only work and edit for modifying existing files.
---

# Write

Use this skill for creating new files or new capability surfaces.

## Core Flow

1. Identify the new artifact and its owner layer: endpoint, service, repository, worker, config, docs, tests, or skill.
2. Read `.codex/skills/project/SKILL.md`, then inspect nearby examples before designing the new file.
3. Keep the first implementation narrow and consistent with existing patterns.
4. Add only the references or support files the new asset needs. Do not add workflow automation unless the user explicitly asks.
5. Validate with the smallest relevant command from the project quality reference; use `uv run` for Python commands.
6. If behavior changed or a new capability was added, consider loading `add-tests` for focused pytest coverage.
7. If files were modified, append the Change Summary block from `.codex/skills/project/references/handoff.md`.

## Progressive Disclosure

- Read [references/new-assets.md](references/new-assets.md) when creating new backend files, docs, configs, migrations, scripts, or local skills.
