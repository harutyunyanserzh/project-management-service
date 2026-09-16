import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.base import ProjectRole


class ProjectCreate(BaseModel):
    """Payload for POST /projects."""

    name: str
    description: str | None = None

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be blank")
        return v


class ProjectUpdate(BaseModel):
    """Payload for PUT /project/{id}/info. Both fields optional (partial update)."""

    name: str | None = None
    description: str | None = None

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("name must not be blank")
        return v


class ProjectRead(BaseModel):
    """Full project details returned to a user who has access to it."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    owner_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    my_role: ProjectRole  # the requesting user's role on this project
    documents: list["DocumentRead"] = Field(default_factory=list)


# Imported here (not at module top) to avoid a circular import between the
# project and document schema modules; DocumentRead only needs primitives.
from app.schemas.document import DocumentRead

ProjectRead.model_rebuild()
