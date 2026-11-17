"""Unit tests for the AI building blocks (no API, no database)."""

import uuid

import pytest

from app.ai.chunking import split_pages
from app.ai.embeddings import HashEmbeddings, embedding_model_name
from app.ai.prompts import extractive_answer, format_context
from app.ai.text_extraction import TextExtractionError, extract_text
from app.ai.vector_store import ScoredChunk, _cosine
from app.models.ai import DocumentChunk
from tests.ai_helpers import DOCX_CONTENT_TYPE, make_docx, make_pdf


def _scored(content: str, page: int | None = None, name: str = "doc.pdf") -> ScoredChunk:
    chunk = DocumentChunk(
        id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        chunk_index=0,
        page_number=page,
        content=content,
        embedding=[],
        embedding_model="hash:8",
    )
    return ScoredChunk(chunk=chunk, file_name=name, score=0.9)


def test_pdf_extraction_keeps_page_numbers():
    pages = extract_text(make_pdf(["First page text", "Second page text"]), "application/pdf")
    assert [(p.page_number, p.text) for p in pages] == [
        (1, "First page text"),
        (2, "Second page text"),
    ]


def test_docx_extraction_includes_tables():
    data = make_docx(["Budget overview"], [["Item", "Cost"], ["Design", "10,000 USD"]])
    pages = extract_text(data, DOCX_CONTENT_TYPE)
    assert len(pages) == 1 and pages[0].page_number is None
    assert "Budget overview" in pages[0].text
    assert "Design | 10,000 USD" in pages[0].text


def test_extraction_errors_are_explicit():
    with pytest.raises(TextExtractionError):
        extract_text(b"not a pdf", "application/pdf")
    with pytest.raises(TextExtractionError):
        extract_text(b"anything", "image/png")


def test_chunks_respect_size_and_overlap():
    from app.ai.text_extraction import PageText

    words = " ".join(f"word{i}" for i in range(400))
    chunks = split_pages([PageText(page_number=3, text=words)], chunk_size=200, chunk_overlap=50)

    assert len(chunks) > 1
    assert all(len(c.content) <= 200 for c in chunks)
    assert all(c.page_number == 3 for c in chunks)
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    # Overlap: the end of one chunk reappears at the start of the next
    assert chunks[0].content.split()[-1] in chunks[1].content


def test_hash_embeddings_rank_shared_words_higher():
    embeddings = HashEmbeddings(dimensions=256)
    query = embeddings.embed_query("launch deadline")
    relevant, unrelated = embeddings.embed_documents(
        ["The launch deadline is in March.", "Yoga classes run every Tuesday."]
    )
    assert _cosine(query, relevant) > _cosine(query, unrelated)
    assert embeddings.embed_query("Launch Deadline") == query  # deterministic, case-insensitive


def test_embedding_model_name_reflects_settings(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "ollama")
    monkeypatch.setattr(settings, "OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")
    assert embedding_model_name() == "ollama:nomic-embed-text"


def test_context_is_numbered_and_respects_budget():
    chunks = [_scored("a" * 100, page=1), _scored("b" * 100, page=2), _scored("c" * 100)]

    context = format_context(chunks, budget=250)

    assert context.startswith("[1] (doc.pdf, page 1)")
    assert "[2] (doc.pdf, page 2)" in context
    assert "[3]" not in context  # dropped: it would exceed the budget


def test_extractive_answer_truncates_long_passages():
    answer = extractive_answer([_scored("word " * 200, page=4)], excerpt_chars=50)
    assert "[1] doc.pdf, page 4:" in answer
    assert answer.endswith("...")
