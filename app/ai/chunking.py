"""Split document text into overlapping chunks small enough to embed and to fit in a prompt."""

from dataclasses import dataclass

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.ai.text_extraction import PageText
from app.core.config import settings


@dataclass
class TextChunk:
    chunk_index: int
    page_number: int | None
    content: str


def split_pages(
    pages: list[PageText], chunk_size: int | None = None, chunk_overlap: int | None = None
) -> list[TextChunk]:
    """Split each page separately so every chunk keeps an accurate page number.

    The recursive splitter tries paragraph breaks first, then lines, then sentences,
    then words, so chunks rarely cut a sentence in half. The overlap repeats a little
    text between neighbouring chunks so a fact that sits on a boundary is not lost.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size or settings.CHUNK_SIZE,
        chunk_overlap=chunk_overlap if chunk_overlap is not None else settings.CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    chunks: list[TextChunk] = []
    for page in pages:
        for piece in splitter.split_text(page.text):
            piece = piece.strip()
            if piece:
                chunks.append(
                    TextChunk(chunk_index=len(chunks), page_number=page.page_number, content=piece)
                )
    return chunks
