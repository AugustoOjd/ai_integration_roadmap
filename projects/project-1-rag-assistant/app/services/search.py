import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentChunk
from app.services.embeddings import embedding_service

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SearchHit:
    """Un chunk recuperado, con lo necesario para citarlo.

    Dataclass y no schema de Pydantic: este servicio no sabe nada de HTTP, asi
    que sirve igual para la ruta de busqueda que para el pipeline de RAG.
    """

    chunk_id: str
    text: str
    source: str
    page: int | None
    section: str | None
    similarity: float


async def search_chunks(db: AsyncSession, query: str, top_k: int) -> list[SearchHit]:
    """Los top_k chunks mas parecidos a `query`.

    La query se embebe con el MISMO modelo que los chunks: vectores de modelos
    distintos no son comparables.
    """
    query_embedding = await embedding_service.embed(query)

    # cosine_distance() lo aporta el tipo Vector de pgvector y emite el operador
    # `embedding <=> :param`, que es el que casa con vector_cosine_ops del indice.
    # El IDE no lo autocompleta: viene del comparator_factory, resuelto en runtime.
    distance = DocumentChunk.embedding.cosine_distance(query_embedding)

    stmt = (
        select(DocumentChunk, Document.filename, (1 - distance).label("similarity"))
        # join y no outerjoin: un chunk sin documento padre no puede existir.
        .join(Document, Document.id == DocumentChunk.document_id)
        # Un chunk sin embedding no tiene distancia con nada.
        .where(DocumentChunk.embedding.is_not(None))
        # ORDER BY por la distancia cruda, no por similarity: `1 - (a <=> b)` es
        # una expresion derivada y el indice no la reconoce.
        .order_by(distance)
        .limit(top_k)
    )

    filas = await db.execute(stmt)

    hits = [
        SearchHit(
            chunk_id=str(chunk.id),
            text=chunk.chunk_text,
            source=filename,
            page=chunk.page,
            section=chunk.section,
            similarity=similarity,
        )
        for chunk, filename, similarity in filas
    ]

    logger.info("SEARCH %r -> %d hits", query, len(hits))
    return hits
