import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Note(Base):
    __tablename__ = "notes"

    # Generated in Python (default=uuid.uuid4) rather than by Postgres, so we already
    # know the id before the INSERT happens
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(nullable=False)
    content: Mapped[str] = mapped_column(nullable=False)

    # server_default=func.now(): Postgres itself stamps this at INSERT time,
    # so it's correct even if the app server's clock is off
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
