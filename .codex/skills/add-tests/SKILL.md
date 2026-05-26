---
name: add-tests
description: Add or update pytest coverage for Dewflow backend. Use when the user asks to add tests, improve coverage, test a bug fix, write unit/component/integration tests, or verify backend behavior with pytest.
---

# Add Tests

Use this skill for test-only work or test coverage paired with a code change.

## Core Flow

1. Identify what behavior changed or needs protection.
2. Read nearby tests, fixtures, `pyproject.toml`, and any test conventions before adding files.
3. Choose the lowest test layer that proves the behavior.
4. Mirror existing fixture, marker, naming, and assertion style.
5. Run the focused pytest command through `uv run`, or explain why it was not run.
6. If files were modified, append the Change Summary block from `.codex/skills/project/references/handoff.md`.

## Progressive Disclosure

- Read [references/pytest-layering.md](references/pytest-layering.md) to select test layer, placement, markers, and verification commands.
