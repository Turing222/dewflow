#!/usr/bin/env python3
"""Audit pytest markers for tests that touch real external capabilities.

职责：扫描测试源码中的真实依赖特征并校验 pytest marker；边界：只做保守静态检查，不推断 fake/mock；副作用：发现缺失 marker 时以非零状态退出。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TESTS_ROOT = PROJECT_ROOT / "tests"


@dataclass(frozen=True)
class MarkerRule:
    name: str
    marker: str
    patterns: tuple[re.Pattern[str], ...]


@dataclass(frozen=True)
class Violation:
    path: Path
    line_number: int
    rule_name: str
    marker: str
    text: str


EXCLUDED_PATH_PARTS = {
    "__pycache__",
    "manual",
}

RULES: tuple[MarkerRule, ...] = (
    MarkerRule(
        name="real database connection",
        marker="requires_db",
        patterns=(re.compile(r"\bcreate_async_engine\s*\("),),
    ),
    MarkerRule(
        name="real Redis connection",
        marker="requires_redis",
        patterns=(re.compile(r"\bredis\.from_url\s*\("),),
    ),
    MarkerRule(
        name="real TaskIQ worker or enqueue",
        marker="requires_taskiq",
        patterns=(
            re.compile(r"\.kiq\s*\("),
            re.compile(r"\btaskiq\s+worker\b"),
        ),
    ),
    MarkerRule(
        name="real S3 client",
        marker="requires_s3",
        patterns=(
            re.compile(r"\bboto3\.client\s*\("),
            re.compile(r"\baioboto3\.Session\s*\("),
            re.compile(r"\bTEST_S3_ENDPOINT_URL\b"),
        ),
    ),
    MarkerRule(
        name="real LLM credential",
        marker="requires_llm",
        patterns=(re.compile(r"\bTEST_LLM_API_KEY\b"),),
    ),
)


def iter_test_files() -> list[Path]:
    return [
        path
        for path in sorted(TESTS_ROOT.rglob("test_*.py"))
        if not EXCLUDED_PATH_PARTS.intersection(path.relative_to(TESTS_ROOT).parts)
    ]


def has_marker(source: str, marker: str) -> bool:
    return f"pytest.mark.{marker}" in source


def is_smoke_file(path: Path, source: str) -> bool:
    return "smoke" in path.relative_to(TESTS_ROOT).parts or has_marker(source, "smoke")


def find_violations(path: Path) -> list[Violation]:
    source = path.read_text(encoding="utf-8")
    if is_smoke_file(path, source):
        return []

    lines = source.splitlines()
    violations: list[Violation] = []
    for rule in RULES:
        if has_marker(source, rule.marker):
            continue
        for line_number, line in enumerate(lines, start=1):
            if any(pattern.search(line) for pattern in rule.patterns):
                violations.append(
                    Violation(
                        path=path,
                        line_number=line_number,
                        rule_name=rule.name,
                        marker=rule.marker,
                        text=line.strip(),
                    )
                )
                break
    return violations


def find_smoke_marker_violations(path: Path) -> list[Violation]:
    source = path.read_text(encoding="utf-8")
    if "smoke" not in path.relative_to(TESTS_ROOT).parts or has_marker(source, "smoke"):
        return []
    return [
        Violation(
            path=path,
            line_number=1,
            rule_name="smoke test file",
            marker="smoke",
            text="file is under tests/smoke",
        )
    ]


def main() -> int:
    violations: list[Violation] = []
    for path in iter_test_files():
        violations.extend(find_smoke_marker_violations(path))
        violations.extend(find_violations(path))

    if not violations:
        print("Test marker audit passed.")
        return 0

    print("Test marker audit failed:")
    for violation in violations:
        rel_path = violation.path.relative_to(PROJECT_ROOT)
        print(
            f"- {rel_path}:{violation.line_number} uses {violation.rule_name} "
            f"but is missing pytest.mark.{violation.marker}: {violation.text}"
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
