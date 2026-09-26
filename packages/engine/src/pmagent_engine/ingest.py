"""Generic document ingestion: any file extension in, normalized markdown out.

Subagents only ever read markdown through the standard deepagents read_file
tool. Rather than writing a separate reader for every possible extension, we
normalize everything to markdown ONCE at ingest time:

    docx / pptx / xlsx / pdf / html / csv / ...  --(markitdown)-->  .md

Originals are kept too, so nothing is lossy — normalization is just what the
agents read; the source of truth for a human is still the original file.

    pip install markitdown
"""
from __future__ import annotations

import shutil
from pathlib import Path

from markitdown import MarkItDown

from .config import ProjectConfig

_PLAIN_TEXT_EXTS = {".md", ".markdown", ".txt", ".rst"}
_converter = MarkItDown()


def ingest_doc(config: ProjectConfig, src_path: str) -> str:
    """Copy src_path into docs/originals/ and write a normalized .md counterpart
    into docs/normalized/. Returns the normalized path, relative to .pmagent/.
    """
    src = Path(src_path)
    if not src.exists():
        raise FileNotFoundError(src_path)

    docs_dir = Path(config.pmagent_dir) / "docs"
    originals_dir = docs_dir / "originals"
    normalized_dir = docs_dir / "normalized"
    originals_dir.mkdir(parents=True, exist_ok=True)
    normalized_dir.mkdir(parents=True, exist_ok=True)

    shutil.copy2(src, originals_dir / src.name)

    normalized_path = normalized_dir / f"{src.stem}.md"
    if src.suffix.lower() in _PLAIN_TEXT_EXTS:
        normalized_path.write_text(src.read_text(errors="ignore"))
    else:
        normalized_path.write_text(_converter.convert(str(src)).text_content)

    rel = normalized_path.relative_to(config.pmagent_dir)
    with open(docs_dir / "manifest.md", "a") as f:
        f.write(f"- `{src.name}` -> `{rel}`\n")

    return str(rel)
