import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column


class TimestampMixin:
    """Adds created_at / updated_at columns, managed by the database."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class UUIDPKMixin:
    """Adds a UUID primary key, generated server-side by Python (uuid4)."""

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )


class ProjectRole(str, enum.Enum):
    """Two access levels, per project spec.

    OWNER: creator of the project. Full control, including delete and invite.
    PARTICIPANT: invited user. Can read/update project info and documents,
                 but cannot delete the project or invite others.
    """

    OWNER = "owner"
    PARTICIPANT = "participant"
