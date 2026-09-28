"""Conversation titles, made from the first message by plain rules: no model call, so a title
costs nothing and is there the moment the conversation starts.

"Hi, can you please summarise the board in one short paragraph?"
    -> "Summarise the board in one short paragraph"
"In three short sentences, what is this project about?" -> "What is this project about"

People rename a conversation whenever they like (PATCH .../agent/threads/{id}).
"""
from __future__ import annotations

import re

MAX_WORDS = 7
MAX_CHARS = 60
NEW_CONVERSATION = "New conversation"

# Openers that say nothing about the topic, removed from the start (repeatedly, longest first).
_FILLER = sorted(
    [
        "hi", "hello", "hey", "ok", "okay", "so", "please", "pls", "kindly", "thanks", "thank you",
        "can you", "could you", "would you", "will you", "can we", "could we", "should we",
        "i want you to", "i'd like you to", "i would like you to", "i need you to",
        "i want to", "i'd like to", "i would like to", "i need to",
        "help me", "let's", "lets", "let us",
        "tell me about", "tell me", "show me", "give me",
    ],
    key=len,
    reverse=True,
)
_FILLER_RE = re.compile(r"^(?:" + "|".join(re.escape(f) for f in _FILLER) + r")\b[\s,!.:;-]*", re.IGNORECASE)
# A short framing clause before the real request: "In one sentence, ...", "For the web app, ...".
_LEAD_CLAUSE_RE = re.compile(
    r"^(?:in|for|as|with|using|based on|given|from|on)\b[^,.?!\n]{0,40},\s*", re.IGNORECASE
)
_SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s|\n")


def title_from_message(message: str) -> str:
    text = re.sub(r"[ \t]+", " ", message.strip())
    # Peel openers off the whole message first, so "Hi! What's blocked?" isn't titled "Hi".
    rest = text
    for _ in range(6):  # "Hi, could you please tell me ..." peels off in a few passes
        stripped = _FILLER_RE.sub("", rest, count=1)
        stripped = _LEAD_CLAUSE_RE.sub("", stripped, count=1)
        if stripped == rest:
            break
        rest = stripped.strip()
    first = _SENTENCE_END_RE.split(rest, maxsplit=1)[0].strip()
    first = first.strip(" \"'`*#").rstrip(".!?:;,")
    if not first:
        # Nothing but pleasantries: fall back to the start of the message itself.
        first = text.split("\n", 1)[0].strip(" \"'`*#").rstrip(".!?:;,")
    words = first.split()
    title = " ".join(words[:MAX_WORDS])
    if len(title) > MAX_CHARS:
        title = title[:MAX_CHARS].rsplit(" ", 1)[0]
    if len(words) > MAX_WORDS or len(title) < len(" ".join(words)):
        title = title.rstrip(",;:-") + "…"
    return (title[:1].upper() + title[1:]) if title else NEW_CONVERSATION
