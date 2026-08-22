import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.note import Note
from app.services.embeddings import embedding_service

logger = logging.getLogger(__name__)


async def search_notes(
    db: AsyncSession, query: str, top_k: int
) -> list[tuple[Note, float]]:
    """Busca las top_k notas más parecidas a `query`.

    La query se embebe con el MISMO modelo que las notas: vectores de modelos
    distintos no son comparables.
    """
    query_embedding = await embedding_service.embed(query)

    # cosine_distance() lo aporta el tipo Vector de pgvector y emite el operador
    # `embedding <=> :param`, que es el que casa con vector_cosine_ops del índice.
    # El IDE no lo autocompleta: viene del comparator_factory del tipo Vector,
    # que solo se resuelve en runtime.
    distance = Note.embedding.cosine_distance(query_embedding)

    stmt = (
        select(Note, (1 - distance).label("similarity"))
        # Una nota sin embedding no tiene distancia con nada.
        .where(Note.embedding.is_not(None))
        # ORDER BY por la distancia cruda, no por similarity: `1 - (a <=> b)` es
        # una expresión derivada y el índice no la reconoce.
        .order_by(distance)
        .limit(top_k)
    )

    # debug (no info): el SQL solo interesa cuando algo va mal.
    logger.debug("SQL: %s", stmt)

    result = await db.execute(stmt)
    # Cada fila trae la entidad y la columna calculada; se acceden por nombre.
    return [(row.Note, row.similarity) for row in result]
