# Config Policy

Use this reference when deciding whether a value belongs in config or code.

## Rule Of Thumb

If changing a value should require zero code changes and zero test changes, it is config. If changing it changes algorithm semantics, it is code.

## Hardcode

Use code-level constants for:

- Algorithm implementation details, such as regex patterns, character sets, and tokenization rules.
- Logic-coupled thresholds where changing the value silently breaks correctness.
- Data definitions, such as what counts as punctuation or a keyword.

## Config

Use env vars or YAML for:

- Tuning knobs for search relevance, ranking quality, or similar experimentation.
- Environment-specific values for dev, staging, and production.
- Model-dependent parameters that change with downstream model or embedding providers.
- Ops-adjustable thresholds, limits, timeouts, and batch sizes.

## Mechanism

| Mechanism | When |
|-----------|------|
| `AISettings` | 1-3 related tuning params; matches existing `RAG_*` pattern |
| YAML config plus Pydantic schema | Complex nested config, or params likely to grow into a subdomain |
| Module-level constant | Algorithm detail only, such as regex or character set |

## Test

If you would tell someone "just change the env var, do not touch the code", put it in config.
