import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

# Las dos clases viven en el mismo archivo porque se referencian entre sí:
# separarlas obliga a un import circular o a trucos con TYPE_CHECKING.


class Document(Base):
    """Un archivo subido. El padre de sus chunks."""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)

    # El texto completo extraído. Duplica lo que ya está en los chunks, a
    # propósito: permite re-trocear con otro tamaño sin volver a subir el PDF.
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
    """Un trozo de texto de un documento, en el orden en que aparece."""

    __tablename__ = "document_chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # ondelete CASCADE lo aplica Postgres; el cascade del relationship solo actúa
    # si borras vía ORM. Hacen falta los dos.
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )

    chunk_text: Mapped[str] = mapped_column(nullable=False)

    # Posición dentro del documento, desde 0. Sin esto no se puede reconstruir
    # el orden ni saber qué chunk va antes de cuál.
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped[Document] = relationship(back_populates="chunks")

    __table_args__ = (
        # Dos chunks del mismo documento no pueden ocupar la misma posición.
        UniqueConstraint("document_id", "chunk_index", name="uq_chunk_document_index"),
        # Postgres NO indexa las foreign keys automáticamente, y toda consulta
        # de chunks filtra por document_id.
        Index("ix_chunks_document_id", "document_id"),
    )
