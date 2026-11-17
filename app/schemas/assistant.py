import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    mode: Literal["rag", "agent"] = "rag"


class Source(BaseModel):
    number: int  # matches the [n] citations in the answer
    document_id: uuid.UUID
    file_name: str
    page_number: int | None
    chunk_index: int
    score: float
    label: str
    excerpt: str


class AskResponse(BaseModel):
    request_id: uuid.UUID
    answer: str
    mode: Literal["rag", "agent"]
    sources: list[Source]
    tool_calls: list[str]
    used_fallback: bool
    warning: str | None
    provider: str
    model: str
    latency_ms: int
    input_tokens: int | None
    output_tokens: int | None


class ChatMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: str
    content: str
    sources: list[Source] | None
    created_at: datetime


class FeedbackRequest(BaseModel):
    helpful: bool


class ReindexResponse(BaseModel):
    documents: int
    chunks: int
    failed: list[str]


class AssistantStatus(BaseModel):
    llm_provider: str
    llm_model: str
    embedding_model: str
    documents: int
    indexed_documents: int
    chunks: int


class AssistantStats(BaseModel):
    requests: int
    avg_latency_ms: float | None
    fallback_rate: float | None
    avg_top_score: float | None
    total_input_tokens: int
    total_output_tokens: int
    feedback_count: int
    helpful_rate: float | None
