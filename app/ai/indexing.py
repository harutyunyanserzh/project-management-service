"""Indexing pipeline: stored file -> text -> chunks -> embeddings -> document_chunks table."""

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

import app.db.session as db_session_module
from app.ai import vector_store
from app.ai.chunking import split_pages
from app.ai.embeddings import embedding_model_name, get_embeddings
from app.ai.text_extraction import extract_text
from app.models.document import Document
from app.services import storage

logger = logging.getLogger(__name__)


@dataclass
class IndexResult:
    document_id: uuid.UUID
    chunks: int
    error: str | None = None


def index_document(db: Session, document: Document) -> IndexResult:
    """Index one document. Raises on failure; the caller decides how to handle it."""
    data, _ = storage.download_file(document.s3_key)
    pages = extract_text(data, document.content_type)
    chunks = split_pages(pages)

    vectors = get_embeddings().embed_documents([c.content for c in chunks]) if chunks else []
    count = vector_store.replace_document_chunks(
        db, document, chunks, vectors, embedding_model_name()
    )
    db.commit()
    logger.info("Indexed document %s into %d chunks", document.id, count)
    return IndexResult(document_id=document.id, chunks=count)


def index_document_safely(db: Session, document: Document) -> IndexResult:
    """Index a document but never raise: a failed index must not break uploads."""
    try:
        return index_document(db, document)
    except Exception as exc:
        db.rollback()
        logger.warning("Could not index document %s: %s", document.id, exc)
        return IndexResult(document_id=document.id, chunks=0, error=str(exc))


def index_document_in_background(document_id: uuid.UUID) -> None:
    """Entry point for FastAPI BackgroundTasks, which run after the response is sent.

    It opens its own database session because the request's session is closed by then.
    """
    db = db_session_module.SessionLocal()
    try:
        document = db.get(Document, document_id)
        if document is not None:
            index_document_safely(db, document)
    finally:
        db.close()
