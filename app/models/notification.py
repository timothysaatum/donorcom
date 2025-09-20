import uuid
from sqlalchemy import String, DateTime, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime, timezone
from app.db.base import Base


class Notification(Base):
    __tablename__ = "notifications"

    # --- Columns ---
    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now(timezone.utc))

    # --- Relationships ---
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
    )

    user = relationship("User", back_populates="notifications")

    # --- Methods ---
    def __str__(self) -> str:
        return f"Notification({self.title}, {self.message}, Read: {self.is_read})"

    def mark_as_read(self):
        self.is_read = True
        self.updated_at = datetime.now(timezone.utc)

    def mark_as_unread(self):
        self.is_read = False
        self.updated_at = datetime.now(timezone.utc)
        