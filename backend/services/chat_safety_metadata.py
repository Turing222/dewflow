"""Chat safety metadata helpers.

职责：统一生成对话安全护栏、回答结果和 badcase 飞轮候选元数据。
边界：本模块只做轻量规则判断和 JSON 结构构造，不查询数据库、不调用外部安全模型。
"""

from dataclasses import dataclass
from enum import StrEnum

SCHEMA_VERSION = 1
SAFETY_REFUSAL_MESSAGE = "抱歉，这个请求涉及安全或权限风险，暂时无法回答。"


class ResponseOutcome(StrEnum):
    ANSWERED = "answered"
    REFUSED = "refused"
    BLOCKED = "blocked"
    FAILED = "failed"


class GuardrailAction(StrEnum):
    ALLOW = "allow"
    BLOCK = "block"


class GuardrailReason(StrEnum):
    PERMISSION_OR_PRIVACY_RISK = "permission_or_privacy_risk"
    UNSAFE_OUTPUT = "unsafe_output"


class BadcaseSeverity(StrEnum):
    P0 = "p0"
    P1 = "p1"


class BadcaseReason(StrEnum):
    SHOULD_REFUSE_BUT_ANSWERED = "should_refuse_but_answered"
    PERMISSION_OR_PRIVACY_RISK = "permission_or_privacy_risk"
    EMPTY_RETRIEVAL_REFUSAL = "empty_retrieval_refusal"
    WRONG_OR_UNHELPFUL_ANSWER = "wrong_or_unhelpful_answer"
    SHOULD_ANSWER_BUT_REFUSED = "should_answer_but_refused"


@dataclass(frozen=True)
class GuardrailDecision:
    """轻量护栏判断结果。"""

    triggered: bool
    reason: str | None = None


def build_safety_metadata(
    *,
    response_outcome: ResponseOutcome,
    input_decision: GuardrailDecision | None = None,
    output_decision: GuardrailDecision | None = None,
    original_unsafe_output: str | None = None,
    badcase_severity: BadcaseSeverity | None = None,
    badcase_reason: BadcaseReason | None = None,
) -> dict[str, object]:
    input_triggered = bool(input_decision and input_decision.triggered)
    output_triggered = bool(output_decision and output_decision.triggered)
    is_badcase = badcase_severity is not None and badcase_reason is not None
    return {
        "schema_version": SCHEMA_VERSION,
        "response_outcome": response_outcome.value,
        "guardrail": {
            "input": {
                "triggered": input_triggered,
                "action": (
                    GuardrailAction.BLOCK.value
                    if input_triggered
                    else GuardrailAction.ALLOW.value
                ),
                "reason": input_decision.reason if input_decision else None,
            },
            "output": {
                "triggered": output_triggered,
                "action": (
                    GuardrailAction.BLOCK.value
                    if output_triggered
                    else GuardrailAction.ALLOW.value
                ),
                "reason": output_decision.reason if output_decision else None,
                "original_unsafe_output": original_unsafe_output,
            },
        },
        "badcase": {
            "is_badcase": is_badcase,
            "severity": badcase_severity.value if badcase_severity else None,
            "reason": badcase_reason.value if badcase_reason else None,
            "source": "auto",
            "status": "open",
        },
    }


def evaluate_input_guardrail(query_text: str) -> GuardrailDecision:
    lowered = query_text.lower()
    risky_intents = ("泄露", "窃取", "绕过权限", "导出隐私", "dump")
    risky_targets = ("密码", "token", "api key", "密钥", "身份证", "手机号")
    if any(intent in lowered for intent in risky_intents) and any(
        target in lowered for target in risky_targets
    ):
        return GuardrailDecision(True, GuardrailReason.PERMISSION_OR_PRIVACY_RISK.value)
    return GuardrailDecision(False)


def evaluate_output_guardrail(content: str) -> GuardrailDecision:
    lowered = content.lower()
    risky_markers = ("密码是", "token 是", "api key 是", "密钥是", "身份证号是")
    if any(marker in lowered for marker in risky_markers):
        return GuardrailDecision(True, GuardrailReason.UNSAFE_OUTPUT.value)
    return GuardrailDecision(False)
