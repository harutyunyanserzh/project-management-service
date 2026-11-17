"""Orchestrates one assistant request: memory -> RAG or agent -> save history -> log metrics."""

import logging
import time
import uuid
from dataclasses import dataclass

from langchain_core.language_models import BaseChatModel
from sqlalchemy.orm import Session

from app.ai import memory
from app.ai.agent import answer_with_agent
from app.ai.llm import model_label
from app.ai.prompts import source_label
from app.ai.rag import AssistantAnswer, answer_with_rag
from app.core.config import settings
from app.models.ai import AIRequestLog

logger = logging.getLogger(__name__)


@dataclass
class AskResult:
    answer: AssistantAnswer
    log: AIRequestLog
    mode: str


def serialize_sources(answer: AssistantAnswer) -> list[dict]:
    return [
        {
            "number": number,
            "document_id": str(item.chunk.document_id),
            "file_name": item.file_name,
            "page_number": item.chunk.page_number,
            "chunk_index": item.chunk.chunk_index,
            "score": round(item.score, 4),
            "label": source_label(item),
            "excerpt": item.chunk.content[:300],
        }
        for number, item in enumerate(answer.sources, start=1)
    ]


def _run(db, project_id, question, mode, history, llm) -> tuple[AssistantAnswer, str]:
    if mode == "agent":
        if llm is None:
            result = answer_with_rag(db, project_id, question, history, llm)
            result.warning = "Agent mode needs a language model (LLM_PROVIDER is 'none'). " + (
                "Used document search instead."
            )
            return result, "rag"
        try:
            return answer_with_agent(db, project_id, question, history, llm), "agent"
        except Exception as exc:
            # e.g. the model does not support tool calling, or the server is unreachable
            logger.warning("Agent failed, falling back to RAG: %s", exc)
            result = answer_with_rag(db, project_id, question, history, llm)
            result.warning = result.warning or (
                f"Agent mode failed ({type(exc).__name__}); answered with document search instead."
            )
            return result, "rag"
    return answer_with_rag(db, project_id, question, history, llm), "rag"


def ask(
    db: Session,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    question: str,
    mode: str,
    llm: BaseChatModel | None,
) -> AskResult:
    history_rows = memory.recent_messages(db, project_id, user_id, settings.CHAT_HISTORY_TURNS)
    history = memory.to_langchain(history_rows)

    started = time.perf_counter()
    answer, used_mode = _run(db, project_id, question, mode, history, llm)
    latency_ms = int((time.perf_counter() - started) * 1000)

    memory.save_exchange(
        db, project_id, user_id, question, answer.answer, serialize_sources(answer)
    )

    provider, model = model_label()
    log = AIRequestLog(
        project_id=project_id,
        user_id=user_id,
        mode=used_mode,
        provider=provider,
        model=model,
        latency_ms=latency_ms,
        input_tokens=answer.input_tokens,
        output_tokens=answer.output_tokens,
        num_sources=len(answer.sources),
        top_score=max((s.score for s in answer.sources), default=None),
        fallback_used=answer.used_fallback,
        error=answer.warning,
    )
    db.add(log)
    db.commit()
    db.refresh(log)

    logger.info(
        "assistant mode=%s provider=%s latency_ms=%d sources=%d fallback=%s tokens_in=%s out=%s",
        used_mode,
        provider,
        latency_ms,
        len(answer.sources),
        answer.used_fallback,
        answer.input_tokens,
        answer.output_tokens,
    )
    return AskResult(answer=answer, log=log, mode=used_mode)
