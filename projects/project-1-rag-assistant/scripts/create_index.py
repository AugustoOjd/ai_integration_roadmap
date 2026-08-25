"""Crea el indice IVFFlat sobre document_chunks.embedding.

    uv run python -m scripts.create_index

Con -m (y no `python scripts/create_index.py`) el cwd entra en sys.path y
`import app` funciona.

Se ejecuta DESPUES de ingerir, nunca antes: ivfflat calcula sus centroides con
los datos presentes al construirlo. Sobre una tabla vacia salen degenerados y
las busquedas devuelven cero filas, sin error.
"""

import asyncio
import logging

from sqlalchemy import func, select, text

from app.database import async_session, engine
from app.models.document import DocumentChunk

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("create_index")

INDICE = "ix_chunks_embedding"


async def main() -> None:
    async with async_session() as session:
        filas = await session.scalar(
            select(func.count()).select_from(DocumentChunk).where(
                DocumentChunk.embedding.is_not(None)
            )
        )
        if not filas:
            logger.error("No hay chunks con embedding. Sube documentos primero.")
            return

        # Regla de pgvector: lists = filas/1000 hasta 1M. Minimo 1.
        lists = max(1, filas // 1000)

        # DROP antes: reconstruir es la forma de recalcular centroides tras
        # ingerir mas documentos.
        await session.execute(text(f"DROP INDEX IF EXISTS {INDICE}"))
        await session.execute(
            text(
                f"CREATE INDEX {INDICE} ON document_chunks "
                f"USING ivfflat (embedding vector_cosine_ops) WITH (lists = {lists})"
            )
        )

        # Sin ANALYZE el planificador estima a ojo y puede ignorar el indice.
        await session.execute(text("ANALYZE document_chunks"))
        await session.commit()

        logger.info("Indice %s creado sobre %d chunks (lists=%d)", INDICE, filas, lists)
        logger.info("Vuelve a correrlo cada vez que ingieras documentos nuevos.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
