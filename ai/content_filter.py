from __future__ import annotations

import re

_PATTERNS = [
    r"игнорируй\s+(все\s+)?(предыдущие\s+)?инструкц",
    r"забудь\s+(свои\s+)?(правила|инструкц)",
    r"ты\s+(теперь\s+|отныне\s+)?в\s+режиме\s+(разработчика|debug|developer)",
    r"покажи\s+(мне\s+)?(системн\w*\s+промпт|system\s?prompt)",
    r"притворись,?\s+что\s+ты\s+(админ|администратор|admin)",
    r"ignore\s+(all\s+)?(previous\s+)?instructions",
    r"you\s+are\s+now\s+(unrestricted|jailbroken|in\s+developer\s+mode)",
    r"reveal\s+(your\s+)?system\s?prompt",
]

_COMPILED = [re.compile(pattern, re.IGNORECASE) for pattern in _PATTERNS]


def check_hard_block(text: str) -> bool:
    return any(pattern.search(text) for pattern in _COMPILED)
