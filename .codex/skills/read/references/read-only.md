# Read-Only Reference

Use this reference when the task is analysis, explanation, discovery, or triage without implementation.

## Boundaries

- Allowed: inspect files, diffs, logs, configs, tests, traces, docs, and command output.
- Allowed: run non-mutating checks when they help answer the question.
- Forbidden: edit files, create files, delete files, run formatters, regenerate assets, update snapshots, or change git state.
- If the user asks for a fix while investigating, produce the fix plan and wait unless the latest request explicitly authorizes implementation.

## Evidence Standard

Tie claims to concrete evidence:

- Source path and line number when code behavior matters.
- Exact command and summarized output when runtime behavior matters.
- Relevant project skill reference when architecture or process matters.
- User-provided logs or stack traces when diagnosing failures.

## Answer Shape

Lead with the answer, then the evidence. Keep speculation separate from confirmed facts.
