"""`<data>` fences for coding prompts: project, repository and CI text an agent must read as data,
never as instructions. The text inside can't end its fence or open another: every `<data` and
`</data` in it is defused, and nothing else is changed, so code and logs stay readable."""
from __future__ import annotations

import re

_DELIMITER = re.compile(r"<(/?)(data)", re.IGNORECASE)


def defuse(text: str) -> str:
    """`text` with every `<data` / `</data` (any case) made inert."""
    return _DELIMITER.sub(lambda m: f"&lt;{m.group(1)}{m.group(2)}", text)


def label(source: str) -> str:
    """A fence's `source` attribute: one line, with nothing that could end the attribute or the tag."""
    return re.sub(r'[\r\n"<>]', " ", source).strip()


def fence(source: str, text: str) -> str:
    """`text` as data from `source`."""
    return f'<data source="{label(source)}">\n{defuse(text)}\n</data>'
