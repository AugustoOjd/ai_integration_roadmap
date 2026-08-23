import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DocumentResponse(BaseModel):
    """Un documento tal como sale por la API.

    Sin `original_text` a propósito: pueden ser cientos de KB que el cliente
    no pidió. Se consulta por sus chunks.
    """

    id: uuid.UUID
    filename: str

    # No es una columna: se cuenta desde la relación. Es el dato que de verdad
    # dice si el troceado funcionó.
    chunks_count: int

    created_at: datetime

    # Permite construir el schema desde el objeto SQLAlchemy (doc.id, ...)
    model_config = ConfigDict(from_attributes=True)


class ChunkResponse(BaseModel):
    """Un trozo, con su posición dentro del documento."""

    id: uuid.UUID
    chunk_index: int
    chunk_text: str

    model_config = ConfigDict(from_attributes=True)
