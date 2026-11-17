"""AI assistant endpoints. Every route reuses the project's existing access rules."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from langchain_core.language_models import BaseChatModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.ai import memory, service
from app.ai.embeddings import embedding_model_name
from app.ai.indexing import index_document_safely
from app.ai.llm import LLMConfigError, get_chat_model, model_label
from app.api.deps import get_project_access_or_403, require_owner
from app.db.session import get_db
from app.models.ai import AIRequestLog, ChatMessage, DocumentChunk
from app.models.document import Document
from app.models.project import ProjectAccess
from app.schemas.assistant import (
    AskRequest,
    AskResponse,
    AssistantStats,
    AssistantStatus,
    ChatMessageRead,
    FeedbackRequest,
    ReindexResponse,
)

router = APIRouter(prefix="/project/{project_id}/assistant", tags=["assistant"])


def chat_model_or_503() -> BaseChatModel | None:
    try:
        return get_chat_model()
    except LLMConfigError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))


@router.post("/ask", response_model=AskResponse)
def ask_assistant(
    body: AskRequest,
    access: ProjectAccess = Depends(get_project_access_or_403),
    db: Session = Depends(get_db),
    llm: BaseChatModel | None = Depends(chat_model_or_503),
) -> AskResponse:
    """Ask a question about this project's documents.

    - **rag** (default): one search, then the model answers from the best passages.
    - **agent**: a LangGraph agent decides which tools to use (search, list, read, project info).
    """
    result = service.ask(db, access.project_id, access.user_id, body.question, body.mode, llm)
    return AskResponse(
        request_id=result.log.id,
        answer=result.answer.answer,
        mode=result.mode,
        sources=service.serialize_sources(result.answer),
        tool_calls=result.answer.tool_calls,
        used_fallback=result.answer.used_fallback,
        warning=result.answer.warning,
        provider=result.log.provider,
        model=result.log.model,
        latency_ms=result.log.latency_ms,
        input_tokens=result.log.input_tokens,
        output_tokens=result.log.output_tokens,
    )


@router.get("/history", response_model=list[ChatMessageRead])
def get_history(
    limit: int = 50,
    access: ProjectAccess = Depends(get_project_access_or_403),
    db: Session = Depends(get_db),
) -> list[ChatMessage]:
    """Your conversation with the assistant in this project. Other members' chats are private."""
    return memory.recent_messages(db, access.project_id, access.user_id, min(max(limit, 1), 200))


@router.delete("/history", status_code=status.HTTP_204_NO_CONTENT)
def clear_history(
    access: ProjectAccess = Depends(get_project_access_or_403),
    db: Session = Depends(get_db),
) -> None:
    memory.clear_history(db, access.project_id, access.user_id)
    db.commit()


@router.post("/feedback/{request_id}", status_code=status.HTTP_204_NO_CONTENT)
def give_feedback(
    request_id: uuid.UUID,
    body: FeedbackRequest,
    access: ProjectAccess = Depends(get_project_access_or_403),
    db: Session = Depends(get_db),
) -> None:
    """Mark an answer as helpful or not. Feeds the helpful_rate in /stats."""
    log = db.get(AIRequestLog, request_id)
    if log is None or log.project_id != access.project_id or log.user_id != access.user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
    log.helpful = body.helpful
    db.commit()


@router.post("/reindex", response_model=ReindexResponse)
def reindex_project(
    access: ProjectAccess = Depends(require_owner),
    db: Session = Depends(get_db),
) -> ReindexResponse:
    """Re-index every document (owner only). Needed after changing the embedding model."""
    documents = db.query(Document).filter(Document.project_id == access.project_id).all()
    results = [index_document_safely(db, document) for document in documents]
    names = {d.id: d.file_name for d in documents}
    return ReindexResponse(
        documents=len(documents),
        chunks=sum(r.chunks for r in results),
        failed=[names[r.document_id] for r in results if r.error],
    )


@router.get("/status", response_model=AssistantStatus)
def assistant_status(
    access: ProjectAccess = Depends(get_project_access_or_403),
    db: Session = Depends(get_db),
) -> AssistantStatus:
    """Which models are configured and how much of the project is indexed."""
    model_name = embedding_model_name()
    chunk_filter = (
        DocumentChunk.project_id == access.project_id,
        DocumentChunk.embedding_model == model_name,
    )
    provider, model = model_label()
    return AssistantStatus(
        llm_provider=provider,
        llm_model=model,
        embedding_model=model_name,
        documents=db.query(Document).filter(Document.project_id == access.project_id).count(),
        indexed_documents=db.query(func.count(func.distinct(DocumentChunk.document_id)))
        .filter(*chunk_filter)
        .scalar(),
        chunks=db.query(DocumentChunk).filter(*chunk_filter).count(),
    )


@router.get("/stats", response_model=AssistantStats)
def assistant_stats(
    access: ProjectAccess = Depends(get_project_access_or_403),
    db: Session = Depends(get_db),
) -> AssistantStats:
    """Monitoring: latency, fallback rate, retrieval scores, token use and user feedback."""
    logs = db.query(AIRequestLog).filter(AIRequestLog.project_id == access.project_id).all()
    count = len(logs)
    scores = [log.top_score for log in logs if log.top_score is not None]
    rated = [log.helpful for log in logs if log.helpful is not None]

    def avg(values):
        return round(sum(values) / len(values), 4) if values else None

    return AssistantStats(
        requests=count,
        avg_latency_ms=avg([log.latency_ms for log in logs]),
        fallback_rate=avg([1.0 if log.fallback_used else 0.0 for log in logs]),
        avg_top_score=avg(scores),
        total_input_tokens=sum(log.input_tokens or 0 for log in logs),
        total_output_tokens=sum(log.output_tokens or 0 for log in logs),
        feedback_count=len(rated),
        helpful_rate=avg([1.0 if h else 0.0 for h in rated]),
    )
