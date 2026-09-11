import uuid

from sqlalchemy import Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import ProjectRole, TimestampMixin, UUIDPKMixin


class Project(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Denormalized convenience pointer to the creator, kept in sync with the
    # ProjectAccess row where role == OWNER. Speeds up "who owns this" checks
    # without a join; the ProjectAccess table remains the source of truth
    # for full membership + role listing.
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    accesses: Mapped[list["ProjectAccess"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    documents: Mapped[list["Document"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Project id={self.id} name={self.name!r}>"


class ProjectAccess(Base, UUIDPKMixin, TimestampMixin):
    """Join table: which users can access which projects, and with what role."""

    __tablename__ = "project_access"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_user"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[ProjectRole] = mapped_column(
        Enum(ProjectRole, name="project_role"), nullable=False, default=ProjectRole.PARTICIPANT
    )

    project: Mapped["Project"] = relationship(back_populates="accesses")
    user: Mapped["User"] = relationship(back_populates="project_accesses")

    def __repr__(self) -> str:
        return f"<ProjectAccess project_id={self.project_id} user_id={self.user_id} role={self.role}>"
