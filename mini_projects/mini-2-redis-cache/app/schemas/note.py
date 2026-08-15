import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class NoteCreate(BaseModel):
    """Request body for POST /notes/ — both fields required."""

    title: str
    content: str


class NoteUpdate(BaseModel):
    """Request body for PUT /notes/{note_id} — full replace, both fields required."""

    title: str
    content: str


class NoteResponse(BaseModel):
    """Response body shape sent back to clients for a single note. Also what we
    serialize to/from Redis for caching (see app/services/cache.py)."""

    id: uuid.UUID
    title: str
    content: str
    created_at: datetime

    # Lets this schema be built directly from a Note SQLAlchemy object
    # (note.id, note.title, ...) instead of only from a dict
    model_config = ConfigDict(from_attributes=True)
