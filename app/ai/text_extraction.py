"""Turn uploaded PDF / DOCX bytes into plain text, keeping page numbers where they exist."""

import io
from dataclasses import dataclass

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class TextExtractionError(Exception):
    """The file could not be read (corrupt, encrypted, or an unsupported type)."""


@dataclass
class PageText:
    page_number: int | None  # 1-based for PDFs; None for DOCX (Word has no fixed pages)
    text: str


def _extract_pdf(data: bytes) -> list[PageText]:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        pages = []
        for number, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if text:
                pages.append(PageText(page_number=number, text=text))
        return pages
    except Exception as exc:  # pypdf raises many different error types
        raise TextExtractionError(f"Could not read PDF: {exc}") from exc


def _extract_docx(data: bytes) -> list[PageText]:
    import docx

    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:
        raise TextExtractionError(f"Could not read DOCX: {exc}") from exc

    parts = [p.text.strip() for p in document.paragraphs if p.text.strip()]
    # Tables often hold the important facts (dates, budgets), so include them row by row
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                parts.append(" | ".join(cells))

    text = "\n".join(parts).strip()
    return [PageText(page_number=None, text=text)] if text else []


def extract_text(data: bytes, content_type: str) -> list[PageText]:
    if content_type == PDF:
        return _extract_pdf(data)
    if content_type == DOCX:
        return _extract_docx(data)
    raise TextExtractionError(f"Unsupported content type: {content_type}")
