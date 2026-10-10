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

import io
import shutil
from pathlib import Path

from markitdown import MarkItDown, StreamInfo

from .config import ProjectConfig

_PLAIN_TEXT_EXTS = {".md", ".markdown", ".txt", ".rst"}
# What to_markdown() accepts: plain text, plus what markitdown's extras convert.
SUPPORTED_EXTENSIONS = frozenset(
    {*_PLAIN_TEXT_EXTS, ".pdf", ".docx", ".pptx", ".xlsx", ".xls", ".html", ".htm", ".csv", ".json", ".xml"}
)
_converter = MarkItDown()


class UnsupportedDocument(ValueError):
    pass


def to_markdown(filename: str, data: bytes) -> str:
    """Convert a document's bytes to markdown. Pure: no files, no project.

    Blocking and CPU-bound (PDF parsing especially); call it off the event loop.
    Raises UnsupportedDocument for unknown formats or files that can't be read.
    """
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise UnsupportedDocument(f"Unsupported format {suffix or '(none)'}")
    if suffix in _PLAIN_TEXT_EXTS:
        return data.decode("utf-8", errors="replace")
    try:
        result = _converter.convert_stream(
            io.BytesIO(data), stream_info=StreamInfo(extension=suffix, filename=filename)
        )
    except Exception as exc:  # markitdown raises many types for corrupt or encrypted files
        raise UnsupportedDocument(f"Couldn't read {filename}: {exc.__class__.__name__}") from exc
    return result.text_content


def ingest_doc(config: ProjectConfig, src_path: str) -> str:
    """Copy src_path into docs/originals/ and write a normalized .md counterpart
    into docs/normalized/. Returns the normalized path, relative to .dotrix/.
    """
    src = Path(src_path)
    if not src.exists():
        raise FileNotFoundError(src_path)

    docs_dir = Path(config.dotrix_dir) / "docs"
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

    rel = normalized_path.relative_to(config.dotrix_dir)
    with open(docs_dir / "manifest.md", "a") as f:
        f.write(f"- `{src.name}` -> `{rel}`\n")

    return str(rel)
