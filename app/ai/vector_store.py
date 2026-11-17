"""Store and search document chunks by vector similarity.

On PostgreSQL the search runs inside the database with pgvector's cosine-distance
operator (`<=>`). On SQLite (tests) the same ranking is computed in Python, so the
behaviour can be tested without a pgvector server.
"""

import math
import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ai.chunking import TextChunk
from app.models.ai import DocumentChunk
from app.models.document import Document


@dataclass
class ScoredChunk:
    chunk: DocumentChunk
    file_name: str
    score: float  # cosine similarity: 1.0 = same direction, 0 = unrelated


def replace_document_chunks(
    db: Session,
    document: Document,
    chunks: list[TextChunk],
    vectors: list[list[float]],
    model_name: str,
) -> int:
    """Delete a document's old chunks and store the new ones (used on upload and replace)."""
    delete_document_chunks(db, document.id)
    for chunk, vector in zip(chunks, vectors, strict=True):
        db.add(
            DocumentChunk(
                document_id=document.id,
                project_id=document.project_id,
                chunk_index=chunk.chunk_index,
                page_number=chunk.page_number,
                content=chunk.content,
                embedding=vector,
                embedding_model=model_name,
            )
        )
    return len(chunks)


def delete_document_chunks(db: Session, document_id: uuid.UUID) -> None:
    db.query(DocumentChunk).filter(DocumentChunk.document_id == document_id).delete(
        synchronize_session=False
    )


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def search(
    db: Session,
    project_id: uuid.UUID,
    query_vector: list[float],
    model_name: str,
    k: int,
    min_score: float = 0.0,
    document_id: uuid.UUID | None = None,
) -> list[ScoredChunk]:
    """Return the k chunks most similar to the query, from ONE project only.

    The project filter is the security boundary: a user can only ever retrieve text
    from projects they already have access to (checked by the API layer).
    """
    if db.get_bind().dialect.name == "postgresql":
        scored = _search_pgvector(db, project_id, query_vector, model_name, k, document_id)
    else:
        scored = _search_in_python(db, project_id, query_vector, model_name, k, document_id)

    results = [item for item in scored if item[1] > min_score]
    if not results:
        return []

    document_ids = list({chunk.document_id for chunk, _ in results})
    names = db.query(Document.id, Document.file_name).filter(Document.id.in_(document_ids)).all()
    file_names = dict(names)
    return [
        ScoredChunk(chunk=chunk, file_name=file_names.get(chunk.document_id, "unknown"), score=s)
        for chunk, s in results
    ]


def _search_pgvector(db, project_id, query_vector, model_name, k, document_id):
    vector_literal = "[" + ",".join(f"{x:.8g}" for x in query_vector) + "]"
    document_filter = "AND document_id = :document_id" if document_id else ""
    sql = text(f"""
        SELECT id, 1 - (embedding <=> CAST(:query AS vector)) AS score
        FROM document_chunks
        WHERE project_id = :project_id AND embedding_model = :model {document_filter}
        ORDER BY embedding <=> CAST(:query AS vector)
        LIMIT :k
        """)
    # Raw SQL bypasses SQLAlchemy's UUID type, and psycopg2 cannot send uuid.UUID
    # objects directly, so ids are passed as strings (Postgres casts them to uuid)
    params = {"query": vector_literal, "project_id": str(project_id), "model": model_name, "k": k}
    if document_id:
        params["document_id"] = str(document_id)
    rows = db.execute(sql, params).all()
    if not rows:
        return []

    ids = [uuid.UUID(str(row.id)) for row in rows]
    chunks = db.query(DocumentChunk).filter(DocumentChunk.id.in_(ids)).all()
    by_id = {chunk.id: chunk for chunk in chunks}
    return [(by_id[i], float(row.score)) for i, row in zip(ids, rows) if i in by_id]


def _search_in_python(db, project_id, query_vector, model_name, k, document_id):
    query = db.query(DocumentChunk).filter(
        DocumentChunk.project_id == project_id, DocumentChunk.embedding_model == model_name
    )
    if document_id:
        query = query.filter(DocumentChunk.document_id == document_id)
    scored = [(chunk, _cosine(query_vector, chunk.embedding)) for chunk in query.all()]
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[:k]
