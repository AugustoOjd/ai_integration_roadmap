import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import EMBEDDING_DIM
from app.database import Base

# Las dos clases viven en el mismo archivo porque se referencian entre si:
# separarlas obliga a un import circular o a trucos con TYPE_CHECKING.


class Document(Base):
    """Un archivo subido. El padre de sus chunks."""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)

    # El texto completo extraido. Duplica lo que ya esta en los chunks, a
    # proposito: permite re-trocear con otro tamano sin volver a subir el PDF.
    original_text: Mapped[str] = mapped_column(nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="document",
        # delete-orphan: borrar el documento borra sus chunks desde el ORM.
        cascade="all, delete-orphan",
        # Sin esto el orden lo decide Postgres, que no garantiza ninguno.
        order_by="DocumentChunk.chunk_index",
    )


class DocumentChunk(Base):
    """Un trozo de texto de un documento, con su vector y su procedencia."""

    __tablename__ = "document_chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # ondelete CASCADE lo aplica Postgres; el cascade del relationship solo actua
    # si borras via ORM. Hacen falta los dos.
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )

    chunk_text: Mapped[str] = mapped_column(nullable=False)

    # Posicion dentro del documento, desde 0. Ordena y ubica el chunk.
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)

    # Vector(384): tipo de pgvector. Emite `vector(384)` en el DDL y convierte
    # a list[float] automaticamente.
    # nullable: el chunk se guarda antes de tener su embedding, y de ahi el
    # `WHERE embedding IS NOT NULL` en las busquedas.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)

    # Metadatos de procedencia, para poder citar. Genericos a proposito: sirven
    # igual para un reglamento que para una novela. Opcionales porque no todo
    # formato los aporta (un .txt no tiene paginas).
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section: Mapped[str | None] = mapped_column(String(120), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped[Document] = relationship(back_populates="chunks")

    __table_args__ = (
        # Dos chunks del mismo documento no pueden ocupar la misma posicion.
        UniqueConstraint("document_id", "chunk_index", name="uq_chunk_document_index"),
        # Postgres NO indexa las foreign keys automaticamente, y toda consulta
        # de chunks filtra por document_id.
        Index("ix_chunks_document_id", "document_id"),
    )


# El indice IVFFlat NO se declara aqui a proposito.
#
# ivfflat calcula sus centroides al CREAR el indice. Puesto en __table_args__ lo
# construiria create_all() con la tabla vacia, y las busquedas devolverian cero
# filas. Se crea con scripts/create_index.py, despues de ingerir.
