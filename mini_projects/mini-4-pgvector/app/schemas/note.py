import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class NoteCreate(BaseModel):
    """Body de POST /notes/."""

    # max_length=200 espeja el String(200) del modelo: sin esto Postgres
    # respondería con un 500 en vez de un 422.
    title: str = Field(min_length=1, max_length=200)
    # min_length=1: embeber "" da un vector sin significado.
    content: str = Field(min_length=1, max_length=10_000)


class NoteResponse(BaseModel):
    """Nota tal como sale por la API.

    Sin el campo `embedding` a propósito: son 384 floats por nota, ruido puro
    para el cliente.
    """

    id: uuid.UUID
    title: str
    content: str
    created_at: datetime

    # Permite construir el schema desde el objeto SQLAlchemy (note.id, ...)
    model_config = ConfigDict(from_attributes=True)


class SearchRequest(BaseModel):
    """Body de POST /notes/search."""

    query: str = Field(min_length=1, max_length=10_000)
    # le=50 acota el LIMIT: el cliente no debería poder pedir la tabla entera.
    top_k: int = Field(default=5, ge=1, le=50)


class SearchResult(NoteResponse):
    """Una nota más su parecido con la query."""

    # No es una columna: la calcula Postgres como 1 - (embedding <=> query).
    # El rango es [-1, 1] porque la distancia coseno va de 0 a 2.
    similarity: float = Field(ge=-1.0, le=1.0)
