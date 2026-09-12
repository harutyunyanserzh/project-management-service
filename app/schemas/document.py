import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DocumentRead(BaseModel):
    """Document metadata returned to the client. Never exposes the raw S3 key."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    file_name: str
    content_type: str
    size_bytes: int
    created_at: datetime
    updated_at: datetime
