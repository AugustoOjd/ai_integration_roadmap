import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DocumentResponse(BaseModel):
    """Un documento tal como sale por la API.

    Sin `original_text` a proposito: pueden ser cientos de KB que el cliente
    no pidio. Se consulta por sus chunks.
    """

    id: uuid.UUID
    filename: str

    # No es una columna: se cuenta en SQL. Es el dato que dice si el troceado
    # funciono.
    chunks_count: int

    created_at: datetime

    # Permite construir el schema desde el objeto SQLAlchemy (doc.id, ...)
    model_config = ConfigDict(from_attributes=True)


class ChunkResponse(BaseModel):
    """Un trozo, con su posicion y su procedencia.

    Sin `embedding`: son 384 floats por chunk, ruido puro para el cliente.
    """

    id: uuid.UUID
    chunk_index: int
    chunk_text: str

    # Lo que permite citar. None en formatos sin paginas.
    page: int | None
    section: str | None

    model_config = ConfigDict(from_attributes=True)
