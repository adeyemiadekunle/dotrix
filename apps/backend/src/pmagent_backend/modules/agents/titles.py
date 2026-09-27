"""Conversation titles: a quick placeholder when a thread starts, then a short title the model
writes from the first exchange (like "Board status and blockers")."""
from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

MAX_TITLE = 60
TITLE_TIMEOUT_SECONDS = 20

TITLE_PROMPT = (
    "Write a title for this conversation about a software project: 3 to 6 words, sentence case, "
    "no quotes, no trailing punctuation, no emoji. Name the topic, not the question "
    '(e.g. "Board status and blockers", "Multi-zone driver epic"). Reply with the title only.'
)

# (model, first message, first reply) -> title, or None to keep the placeholder
Titler = Callable[[Any, str, str], Awaitable[str | None]]


def _clean(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip().strip("\"'`*#").strip()
    text = text.rstrip(".!?:;,")
    if len(text) > MAX_TITLE:
        text = text[:MAX_TITLE].rsplit(" ", 1)[0].rstrip(",;:-") + "…"
    return text[:1].upper() + text[1:]


def placeholder_title(message: str) -> str:
    """Shown until the model's title arrives: the first sentence, trimmed to a few words."""
    first = re.split(r"(?<=[.!?])\s|\n", message.strip(), maxsplit=1)[0]
    words = first.split()
    short = " ".join(words[:8]) + ("…" if len(words) > 8 else "")
    return _clean(short) or "New conversation"


async def generate_title(model: Any, message: str, reply: str) -> str | None:
    """Ask the project's model for a short title. Returns None on any failure (the placeholder
    stays); a title is a nicety, never worth failing or slowing a run for."""
    prompt = f"{TITLE_PROMPT}\n\nUser: {message[:2000]}\n\nAssistant: {reply[:2000]}"
    try:
        response = await asyncio.wait_for(model.ainvoke(prompt), TITLE_TIMEOUT_SECONDS)
    except Exception as exc:  # timeouts, provider errors, anything
        logger.info("title generation skipped: %s", exc.__class__.__name__)
        return None
    content = response.content
    if isinstance(content, list):
        content = "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    title = _clean(str(content).splitlines()[0] if str(content).strip() else "")
    return title or None
