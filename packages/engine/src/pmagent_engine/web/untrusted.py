"""Text from the web is data, never instructions (docs/agents-v2.md §6.1).

Every piece of it reaches the model inside `<web_content source="S3">…</web_content>`, which
the page can't close early, and a small detector flags pages that talk to AI agents, so the
report can say a page tried to.
"""
from __future__ import annotations

import re

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (reason, re.compile(pattern, re.I))
    for reason, pattern in (
        ("asks to ignore instructions",
         r"\b(ignore|disregard|forget|override)\b[^.\n]{0,40}\b(previous|prior|above|earlier|all|your|system)\b"
         r"[^.\n]{0,20}\b(instructions?|prompts?|rules?|directions?)"),
        ("addresses an AI", r"\b(you are|you're|as) (an? )?(ai|llm|language model|assistant|agent)\b"),
        ("addresses an AI", r"\b(attention|note to|dear)\s*,?\s*(ai|llm|assistant|agent|chatbot|gpt|claude|gemini)s?\b"),
        ("mentions a system prompt", r"\b(system prompt|developer message|<\s*/?\s*system\s*>)"),
        ("names our tools", r"\b(write_file|edit_file|create_issue|update_issue|submit_result|fetch_page)\b"),
        ("asks to send data", r"\b(send|post|exfiltrate|upload|leak)\b[^.\n]{0,40}\b(api[ _-]?keys?|tokens?|secrets?|passwords?|credentials)\b"),
    )
)
_HIDDEN = re.compile(r"[​-‏⁠-⁤﻿\U000e0000-\U000e007f]")
_CLOSE = re.compile(r"<\s*/?\s*web_content", re.I)


def suspicious(text: str) -> tuple[str, ...]:
    """Why this text looks like it's trying to instruct an agent (empty when it doesn't)."""
    reasons = [reason for reason, pattern in _PATTERNS if pattern.search(text)]
    if len(_HIDDEN.findall(text)) >= 8:
        reasons.append("contains hidden characters")
    return tuple(dict.fromkeys(reasons))


def wrap(label: str, text: str) -> str:
    """The text as data from source `label`; it can't open or close the wrapper itself."""
    safe = _CLOSE.sub(lambda m: m.group(0).replace("<", "&lt;"), _HIDDEN.sub("", text))
    return f'<web_content source="{label}">\n{safe.strip()}\n</web_content>'
