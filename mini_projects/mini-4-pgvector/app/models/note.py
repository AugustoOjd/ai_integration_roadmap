import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.config import EMBEDDING_DIM
from app.database import Base


class Note(Base):
    __tablename__ = "notes"

    # id generado en Python, así lo conocemos antes del INSERT
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(nullable=False)

    # Vector(384): tipo de pgvector. Emite `vector(384)` en el DDL y convierte
    # a list[float] automáticamente.
    # nullable: la nota puede existir antes que su embedding — de ahí el
    # `WHERE embedding IS NOT NULL` en las búsquedas.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)

    # server_default: lo estampa Postgres, no el reloj del app server
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# El índice IVFFlat NO se declara aquí a propósito.
#
# ivfflat calcula sus centroides al CREAR el índice. Puesto en __table_args__ lo
# construiría create_all() con la tabla vacía: centroides basura, y como solo se
# inspecciona 1 cluster de 100, las búsquedas devuelven cero filas.
#
# Se crea en scripts/benchmark.py, después de cargar datos, que es también lo que
# se hace en producción. Sin índice la búsqueda es exacta y sobra para desarrollo.
