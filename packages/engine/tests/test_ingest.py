import io
import zipfile

import pytest

from dotrix_engine.ingest import UnsupportedDocument, to_markdown


def _docx(text: str) -> bytes:
    """A minimal valid .docx, built by hand (python-docx isn't a dependency)."""
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    document = (
        f'<w:document xmlns:w="{ns}"><w:body>'
        '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Scheduled delivery</w:t></w:r></w:p>'
        f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"
        "</w:body></w:document>"
    )
    content_types = (
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    rels = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Target="word/document.xml" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"/>'
        "</Relationships>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", document)
    return buf.getvalue()


def _xlsx() -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["Hub", "State"])
    ws.append(["Ikeja", "Lagos"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_plain_text_passes_through() -> None:
    assert to_markdown("notes.md", b"# Notes\nhello") == "# Notes\nhello"


def test_docx_is_converted() -> None:
    md = to_markdown("spec.docx", _docx("Merchants can book a delivery slot."))
    assert "Scheduled delivery" in md and "delivery slot" in md


def test_xlsx_is_converted() -> None:
    md = to_markdown("hubs.xlsx", _xlsx())
    assert "Ikeja" in md and "Lagos" in md


def test_unsupported_format() -> None:
    with pytest.raises(UnsupportedDocument):
        to_markdown("run.exe", b"MZ")

