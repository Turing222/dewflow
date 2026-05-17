---
name: project
description: Dewflow backend project rules and context. Use for any work in this repository when Codex needs architecture boundaries, directory ownership, coding conventions, quality gates, operational constraints, commit guidance, or response handoff rules.
---

# Project

Use this skill as the shared project map. Load only the reference needed for the current task.

## References

- [context.md](references/context.md): project overview and directory map.
- [architecture.md](references/architecture.md): web/worker split, dependency injection, and 3-tier call chain.
- [coding.md](references/coding.md): naming, typing, async, comments, and errors.
- [config-policy.md](references/config-policy.md): when to use config, YAML, settings, or code constants.
- [quality.md](references/quality.md): Make targets, `uv run`, Docker checks, and command constraints.
- [handoff.md](references/handoff.md): change summary and commit message conventions.
- [task-mode.md](references/task-mode.md): mode selection, skill collaboration, and `agents/openai.yaml` purpose.

## Use With Mode Skills

After loading the relevant project reference, load exactly one task-mode skill unless the user request clearly needs more:

- `read` for read-only analysis.
- `write` for new files or new capability surfaces.
- `edit` for modifying existing files.
- `add-tests` for pytest coverage.
- `plan` for task breakdowns and dependency-aware planning.

After `write` or `edit`, consider `add-tests` if behavior changed or coverage gaps exist.
