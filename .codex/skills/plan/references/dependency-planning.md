# Dependency Planning Reference

Use this reference when a request has multiple requirements, unclear ordering, or possible parallel work.

## Labels

- `parallel`: can start immediately and does not write the same files as another task.
- `depends_on: N`: should wait for task N because it needs that output or decision.
- `blocking`: must happen first because it determines scope, schema, architecture, or safety.
- `serial`: cannot safely overlap because it touches the same files or state.

## Decomposition Heuristics

- Start from user requirements, not implementation layers.
- Split read-only discovery from write tasks.
- Split code changes from test changes when they can be assigned separately.
- Keep shared contract/schema changes before dependent endpoint, service, repository, or worker work.
- Keep validation close to the task it proves.

## Example

```md
## Plan
1. [blocking] Confirm target behavior and inspect existing service/repository patterns.
2. [parallel] Add service logic after task 1 clarifies the contract.
3. [parallel] Add repository query support after task 1 clarifies persistence needs.
4. [depends_on: 2,3] Wire endpoint behavior once service and repository APIs are stable.
5. [depends_on: 2,3,4] Add focused unit/component tests and run validation.
```
