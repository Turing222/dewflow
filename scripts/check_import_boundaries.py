#!/usr/bin/env python3
"""Lightweight import boundary checker for Web/Worker separation.

Checks:
  - Web application code does not import from backend.worker.tasks.
  - Web-facing application/API code does not import AI runtime modules.
  - Worker code does not import from backend.api.
  - Shared services do not add new FastAPI imports (info only).

Exit 1 on violations, 0 if clean.
"""

import re
from pathlib import Path
from typing import TypedDict

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "backend"

IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+(\S+)", re.MULTILINE)

# ── Rule definitions ──────────────────────────────────────────────────


class ImportBoundaryRule(TypedDict):
    name: str
    desc: str
    files: list[Path]
    forbidden_prefixes: list[str]
    skip_patterns: list[str]


RULES: list[ImportBoundaryRule] = [
    {
        "name": "web-not-import-worker-tasks",
        "desc": "Web application code must not import backend.worker.tasks",
        "files": [
            SRC / "application",
            SRC / "api",
        ],
        "forbidden_prefixes": ["backend.worker.tasks"],
        "skip_patterns": [],
    },
    {
        "name": "web-not-import-ai-runtime",
        "desc": "Web-facing code must not import AI/Worker runtime modules",
        "files": [
            SRC / "application" / "chat" / "web_stream_workflow.py",
            SRC / "application" / "chat" / "web_nonstream_workflow.py",
            SRC / "application" / "knowledge" / "upload_workflow.py",
            SRC / "api",
        ],
        "forbidden_prefixes": [
            "backend.ai",
            "backend.api.deps.ai",
            "backend.application.chat.worker_generation_workflow",
            "backend.application.knowledge.ingestion_workflow",
        ],
        "skip_patterns": [
            "backend/api/deps/ai.py",
        ],
    },
    {
        "name": "worker-not-import-api",
        "desc": "Worker code must not import backend.api",
        "files": [
            SRC / "worker",
            SRC / "application" / "chat" / "worker_generation_workflow.py",
        ],
        "forbidden_prefixes": ["backend.api"],
        "skip_patterns": [],
    },
    {
        "name": "shared-not-import-fastapi",
        "desc": "Shared application/service/infra/core code must not import FastAPI",
        "files": [
            SRC / "application",
            SRC / "core",
            SRC / "infra",
            SRC / "services",
            SRC / "worker",
        ],
        "forbidden_prefixes": ["fastapi"],
        "skip_patterns": [
            "backend/core/exception_handlers.py",
        ],
    },
]


def check_file(filepath: Path, forbidden_prefixes: list[str]) -> list[str]:
    violations: list[str] = []
    try:
        content = filepath.read_text(encoding="utf-8")
    except Exception:
        return violations

    for match in IMPORT_RE.finditer(content):
        module = match.group(1)
        for prefix in forbidden_prefixes:
            if module == prefix or module.startswith(prefix + "."):
                line_no = content[: match.start()].count("\n") + 1
                violations.append(f"  {filepath}:{line_no}  imports {module}")
    return violations


def main() -> int:
    violations_found = 0

    for rule in RULES:
        print(f"[{rule['name']}] {rule['desc']}")
        for file_root in rule["files"]:
            root_path = Path(file_root)
            if root_path.is_file():
                files = [root_path]
            elif root_path.is_dir():
                files = sorted(root_path.rglob("*.py"))
            else:
                continue  # skip if path doesn't exist yet

            for filepath in files:
                if any(pat in str(filepath) for pat in rule.get("skip_patterns", [])):
                    continue
                violations = check_file(filepath, rule["forbidden_prefixes"])
                if violations:
                    for violation in violations:
                        print(violation)
                    violations_found += len(violations)

    if violations_found:
        print(f"\n{violations_found} import boundary violation(s) found.")
        return 1

    print("\nAll import boundaries OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
