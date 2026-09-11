import uuid

from sqlalchemy import BigInteger, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import TimestampMixin, UUIDPKMixin


class Document(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "documents"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    uploaded_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    content_type: Mapped[str] = mapped_column(String(150), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    # Key/path inside the S3 bucket. Never expose this raw to clients;
    # downloads are proxied through GET /document/{id}.
    s3_key: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)

    project: Mapped["Project"] = relationship(back_populates="documents")

    def __repr__(self) -> str:
        return f"<Document id={self.id} file_name={self.file_name!r} project_id={self.project_id}>"
