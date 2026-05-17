---
name: plan
description: Dependency-aware task planning for Dewflow backend work. Use when the user asks for a plan, implementation strategy, task breakdown, execution order, parallelization, estimates, or wants requirements decomposed before code changes.
---

# Plan

Use this skill before execution when the user wants a plan or the work is broad enough that ordering matters.

## Core Flow

1. Restate the goal in one sentence.
2. Split the request by user-visible requirement, then by technical workstream.
3. Mark each task as `parallel`, `depends_on`, or `blocking`.
4. Prefer independent tasks that can run in parallel; mark dependencies explicitly when shared files, schema order, or test setup creates coupling.
5. Include validation per task, but do not automate workflows unless the user asks.

## Output Shape

Use concise Chinese by default:

```md
## Plan
1. [parallel] ...
2. [depends_on: 1] ...
3. [blocking] ...

## Notes
- ...
```

## Progressive Disclosure

- Read [references/dependency-planning.md](references/dependency-planning.md) for dependency labels, decomposition heuristics, and examples.
