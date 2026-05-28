"""Token counting helpers.

职责：为 prompt 预算和信用预检提供 token 估算，优先使用 tiktoken。
边界：本模块只做本地估算，不向模型服务请求真实 usage。
失败处理：tiktoken 不可用或模型无专用编码器时使用保守 fallback。

位置：放在 backend/utils/ 而非 backend/ai/core/ 下，
因为 web 镜像不安装 jinja2，而 backend.ai.core.__init__ 的导入链
会拉入 prompt_manager → jinja2，导致 web 侧无法导入。
"""

import logging
from collections.abc import Sequence
from typing import Any

from backend.models.schemas.chat.dto import ConversationMessage

logger = logging.getLogger(__name__)

_tiktoken_available = False
_encoding_cache: dict[str, Any | None] = {}

try:
    import tiktoken

    _tiktoken_available = True
    logger.info("tiktoken 加载成功，将使用精确的 Token 计算")
except ImportError:
    logger.warning("tiktoken 未安装，将使用字符估算法 (len // 3)")


def _get_encoding(model: str):
    """返回模型编码器；未知模型使用通用编码器。"""
    if model not in _encoding_cache:
        try:
            _encoding_cache[model] = tiktoken.encoding_for_model(model)
        except KeyError:
            logger.debug("模型 '%s' 无专用编码器，将使用字符估算", model)
            _encoding_cache[model] = None
        except Exception as exc:
            logger.warning("加载模型 '%s' 编码器失败，将使用字符估算: %s", model, exc)
            _encoding_cache[model] = None
    return _encoding_cache[model]


def count_tokens(text: str, model: str = "gpt-4") -> int:
    """计算单条文本的 token 数。"""
    if not text:
        return 0

    if _tiktoken_available:
        encoding = _get_encoding(model)
        if encoding is not None:
            return len(encoding.encode(text))

    # 没有 tokenizer 时使用保守字符估算，避免把过长 prompt 放行。
    return max(1, len(text) // 3)


def count_messages_tokens(
    messages: Sequence[dict[str, Any] | ConversationMessage],
    model: str = "gpt-4",
) -> int:
    """按 OpenAI chat 消息格式估算消息列表 token 数。"""
    if not messages:
        return 0

    tokens_per_message = 4  # 每条消息的固定开销

    total = 0
    for msg in messages:
        total += tokens_per_message
        total += count_tokens(msg["content"], model)
        total += count_tokens(msg["role"], model)

    total += 2  # 回复的起始 token 开销
    return total
