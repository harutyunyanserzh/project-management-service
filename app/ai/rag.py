"""Retrieval-Augmented Generation: retrieve relevant chunks, then let the model answer from them."""

import uuid
from dataclasses import dataclass, field

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from sqlalchemy.orm import Session

from app.ai import vector_store
from app.ai.embeddings import embedding_model_name, get_embeddings
from app.ai.prompts import (
    NOT_FOUND_ANSWER,
    RAG_SYSTEM_PROMPT,
    build_rag_user_message,
    extractive_answer,
    format_context,
)
from app.ai.vector_store import ScoredChunk
from app.core.config import settings


@dataclass
class AssistantAnswer:
    answer: str
    sources: list[ScoredChunk] = field(default_factory=list)
    used_fallback: bool = False
    warning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    tool_calls: list[str] = field(default_factory=list)


def message_text(message: BaseMessage) -> str:
    """Chat models return either a string or a list of content blocks; normalise to text."""
    content = message.content
    if isinstance(content, str):
        return content.strip()
    parts = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "".join(parts).strip()


def retrieve(
    db: Session,
    project_id: uuid.UUID,
    query: str,
    k: int | None = None,
    document_id: uuid.UUID | None = None,
) -> list[ScoredChunk]:
    query_vector = get_embeddings().embed_query(query)
    return vector_store.search(
        db,
        project_id,
        query_vector,
        embedding_model_name(),
        k=k or settings.RAG_TOP_K,
        min_score=settings.RAG_MIN_SCORE,
        document_id=document_id,
    )


def retrieval_query(question: str, history: list[BaseMessage]) -> str:
    """Make follow-up questions searchable.

    "When is it due?" on its own retrieves nothing useful. Adding the previous user
    question ("What does the vendor contract say about delivery?") gives the search
    the missing subject.
    """
    previous = [m for m in history if isinstance(m, HumanMessage)]
    if previous:
        return f"{message_text(previous[-1])}\n{question}"
    return question


def answer_with_rag(
    db: Session,
    project_id: uuid.UUID,
    question: str,
    history: list[BaseMessage],
    llm: BaseChatModel | None,
) -> AssistantAnswer:
    chunks = retrieve(db, project_id, retrieval_query(question, history))

    # Nothing relevant: answer directly instead of letting the model guess
    if not chunks:
        return AssistantAnswer(answer=NOT_FOUND_ANSWER)

    if llm is None:
        return AssistantAnswer(answer=extractive_answer(chunks), sources=chunks, used_fallback=True)

    context = format_context(chunks)
    messages = [
        SystemMessage(content=RAG_SYSTEM_PROMPT),
        *history,
        HumanMessage(content=build_rag_user_message(question, context)),
    ]
    try:
        response = llm.invoke(messages)
    except Exception as exc:
        # The model server is down or misconfigured: still give the user the passages
        return AssistantAnswer(
            answer=extractive_answer(chunks),
            sources=chunks,
            used_fallback=True,
            warning=f"The language model is unavailable ({type(exc).__name__}). "
            "Showing the most relevant passages instead.",
        )

    usage = getattr(response, "usage_metadata", None) or {}
    return AssistantAnswer(
        answer=message_text(response) or NOT_FOUND_ANSWER,
        sources=chunks,
        input_tokens=usage.get("input_tokens"),
        output_tokens=usage.get("output_tokens"),
    )
