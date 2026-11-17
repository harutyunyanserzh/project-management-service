"""Helpers for the AI assistant tests: real PDF/DOCX files and fake chat models."""

import io

from langchain_core.messages import AIMessage

DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def make_pdf(pages: list[str]) -> bytes:
    """Build a small but valid PDF with one line of text per page (no extra libraries)."""
    objects: list[bytes] = []
    page_ids = [4 + 2 * i for i in range(len(pages))]

    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for i, text in enumerate(pages):
        safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = f"BT /F1 12 Tf 72 720 Td ({safe}) Tj ET".encode()
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {page_ids[i] + 1} 0 R >>".encode()
        )
        objects.append(
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
        )

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return out.getvalue()


def make_docx(paragraphs: list[str], table: list[list[str]] | None = None) -> bytes:
    import docx

    document = docx.Document()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    if table:
        grid = document.add_table(rows=len(table), cols=len(table[0]))
        for r, row in enumerate(table):
            for c, value in enumerate(row):
                grid.cell(r, c).text = value
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


class FakeChatModel:
    """Stands in for a LangChain chat model. Returns scripted replies and records inputs.

    It supports the two things the app uses: `invoke(messages)` and `bind_tools(tools)`.
    """

    def __init__(
        self, replies: list[AIMessage | str] | None = None, error: Exception | None = None
    ):
        self.replies = [AIMessage(content=r) if isinstance(r, str) else r for r in (replies or [])]
        self.error = error
        self.calls: list[list] = []
        self.bound_tools: list[str] = []

    def bind_tools(self, tools, **kwargs):
        self.bound_tools = [t.name for t in tools]
        return self

    def invoke(self, messages, *args, **kwargs):
        self.calls.append(list(messages))
        if self.error:
            raise self.error
        if not self.replies:
            return AIMessage(content="(no more scripted replies)")
        return self.replies.pop(0)


def tool_call(name: str, args: dict, call_id: str = "call_1") -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])
