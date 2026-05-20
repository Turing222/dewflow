# Task Mode Selection

Use this reference when a request could fit more than one local skill.

## Modes

- `read`: inspect, explain, summarize, compare, diagnose, or answer without file changes.
- `write`: create new code, docs, config, migrations, scripts, or skill assets.
- `edit`: change existing code, docs, config, migrations, scripts, or skill assets.
- `add-tests`: create or update pytest coverage.
- `plan`: decompose work before execution, especially when tasks can run in parallel or have dependencies.

## Ambiguity Rule

Prefer the least invasive mode that satisfies the latest user request. If implementation intent is explicit, choose `write`, `edit`, or `add-tests`; if intent is unclear and risk is high, ask one concise question.

## Collaboration Flow

- After `write` or `edit`, consider `add-tests` when coverage gaps exist or behavior changed.
- After `plan`, switch to the mode skill that owns the next executable step.
- For broad implementation, use `plan` first only when ordering, dependencies, or parallel work matter.

## agents/openai.yaml

Each skill may include `agents/openai.yaml` with `display_name`, `short_description`, and `default_prompt`. Keep these files as generated UI metadata for Codex/OpenAI agent skill lists and chips; they are not runtime backend code.
