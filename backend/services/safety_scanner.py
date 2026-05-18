"""Safety scanner for prompt injection and sensitive data detection.

职责：扫描文本中的提示注入关键词和敏感数据，并提供日志脱敏能力。
边界：本模块是纯规则服务，不查询数据库、不调用外部安全模型、不做 IO。
副作用：无。

WARNING: This module implements a rule-based content filter. It is NOT a
substitute for a real content safety model. It is trivially bypassable via
synonyms, paraphrasing, or character substitution. This implementation exists
for early-stage safety data collection and SHOULD be replaced or augmented
with an ML-based classifier before production deployment.
"""

import re
from dataclasses import dataclass
from enum import StrEnum

# ── Types ────────────────────────────────────────────────────────────


class SafetyCategory(StrEnum):
    OK = "ok"
    INJECTION_RISK = "injection_risk"
    SENSITIVE_DATA_DETECTED = "sensitive_data_detected"


@dataclass(frozen=True)
class SafetyScanResult:
    category: SafetyCategory
    injection_risk: bool
    sensitive_data_risk: bool
    detected_patterns: list[str]


# ── Injection patterns ───────────────────────────────────────────────

_CN_INJECTION_KEYWORDS: tuple[str, ...] = (
    "忽略以上",
    "忽略之前",
    "忽略上面的",
    "你现在是",
    "扮演",
    "输出系统提示",
    "输出 system prompt",
    "越狱",
    "不再遵守",
)

_EN_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bignore\s+(?:previous|above|all)\s+instructions?\b",
        r"\byou\s+are\s+now\b",
        r"\bpretend\s+you\b",
        r"\bjailbreak\b",
        r"\bact\s+as\b",
        r"\bshow\s+(?:me\s+)?(?:your\s+)?instructions\b",
        r"\bdisregard\s+(?:previous|above|all)\s+rules\b",
    )
)


# ── Sensitive data patterns ─────────────────────────────────────────

SENSITIVE_PATTERNS: dict[str, re.Pattern[str]] = {
    "api_key": re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),
    "aws_access_key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "password": re.compile(r"(?i)(?:password|passwd|pwd)\s*[:=]\s*\S{8,}"),
    "generic_secret": re.compile(
        r"(?i)(?:secret|token|credential|private_key)\s*[:=]\s*[A-Za-z0-9_\-/+=]{16,}"
    ),
    "phone_cn": re.compile(r"1[3-9]\d{9}"),
    "email": re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"),
}

_SECRET_PATTERN_NAMES: frozenset[str] = frozenset(
    {"api_key", "aws_access_key", "password", "generic_secret"}
)


# ── Scanner ─────────────────────────────────────────────────────────


class SafetyScanner:
    """Rule-based safety scanner for prompt injection and sensitive data."""

    @staticmethod
    def scan(text: str) -> SafetyScanResult:
        injection_risk = False
        sensitive_data_risk = False
        detected: list[str] = []

        # Check injection patterns
        for kw in _CN_INJECTION_KEYWORDS:
            if kw in text:
                injection_risk = True
                detected.append(kw)

        for pat in _EN_INJECTION_PATTERNS:
            if pat.search(text):
                injection_risk = True
                detected.append(pat.pattern)

        # Check sensitive patterns
        for name, pat in SENSITIVE_PATTERNS.items():
            if pat.search(text):
                sensitive_data_risk = True
                detected.append(name)

        if injection_risk:
            category = SafetyCategory.INJECTION_RISK
        elif sensitive_data_risk:
            category = SafetyCategory.SENSITIVE_DATA_DETECTED
        else:
            category = SafetyCategory.OK

        return SafetyScanResult(
            category=category,
            injection_risk=injection_risk,
            sensitive_data_risk=sensitive_data_risk,
            detected_patterns=detected,
        )

    @staticmethod
    def redact(text: str) -> str:
        """Redact sensitive data from text. Only sensitive patterns are replaced,
        injection keywords are left intact."""
        # API keys / AWS keys → [REDACTED]
        text = SENSITIVE_PATTERNS["api_key"].sub("[REDACTED_API_KEY]", text)
        text = SENSITIVE_PATTERNS["aws_access_key"].sub("[REDACTED_AWS_KEY]", text)

        # Generic secret → [REDACTED]
        text = SENSITIVE_PATTERNS["generic_secret"].sub(
            lambda m: re.sub(r"[:=]\s*\S+", ": [REDACTED]", m.group(0)),
            text,
        )

        # Password → password=[REDACTED]
        text = SENSITIVE_PATTERNS["password"].sub(
            lambda m: re.sub(r"[:=]\s*\S+", "=[REDACTED]", m.group(0)),
            text,
        )

        # Phone → 138****8000
        text = SENSITIVE_PATTERNS["phone_cn"].sub(
            lambda m: m.group(0)[:3] + "****" + m.group(0)[7:], text
        )

        # Email → f***@example.com
        text = SENSITIVE_PATTERNS["email"].sub(
            lambda m: m.group(0)[0] + "***@" + m.group(0).split("@", 1)[1], text
        )

        return text

    @staticmethod
    def has_secret_patterns(scan_result: SafetyScanResult) -> bool:
        """Return True if any detected pattern is a secret-type pattern."""
        return bool(_SECRET_PATTERN_NAMES & frozenset(scan_result.detected_patterns))
