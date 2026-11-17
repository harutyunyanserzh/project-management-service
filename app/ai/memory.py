"""Conversation memory: each user has their own chat history per project."""

import uuid
from datetime import datetime, timedelta, timezone

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from sqlalchemy.orm import Session

from app.models.ai import ChatMessage


def recent_messages(
    db: Session, project_id: uuid.UUID, user_id: uuid.UUID, limit: int
) -> list[ChatMessage]:
    """The last `limit` messages, oldest first."""
    if limit <= 0:
        return []
    rows = (
        db.query(ChatMessage)
        .filter(ChatMessage.project_id == project_id, ChatMessage.user_id == user_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(limit)
        .all()
    )
    return list(reversed(rows))


def to_langchain(messages: list[ChatMessage]) -> list[BaseMessage]:
    """Convert stored rows into the message objects chat models expect.

    Only the last few turns are sent (CHAT_HISTORY_TURNS). That keeps follow-up
    questions working ("and who approves it?") without the prompt growing forever.
    """
    converted: list[BaseMessage] = []
    for message in messages:
        cls = HumanMessage if message.role == "user" else AIMessage
        converted.append(cls(content=message.content))
    return converted


def save_exchange(
    db: Session,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    question: str,
    answer: str,
    sources: list[dict],
) -> None:
    # Timestamps are set here (not by the database) so the question is always ordered
    # before its answer, even on databases with one-second timestamp precision.
    now = datetime.now(timezone.utc)
    db.add(
        ChatMessage(
            project_id=project_id, user_id=user_id, role="user", content=question, created_at=now
        )
    )
    db.add(
        ChatMessage(
            project_id=project_id,
            user_id=user_id,
            role="assistant",
            content=answer,
            sources=sources,
            created_at=now + timedelta(microseconds=1),
        )
    )


def clear_history(db: Session, project_id: uuid.UUID, user_id: uuid.UUID) -> int:
    return (
        db.query(ChatMessage)
        .filter(ChatMessage.project_id == project_id, ChatMessage.user_id == user_id)
        .delete(synchronize_session=False)
    )
