"""Mide la búsqueda sin índice, con IVFFlat y con HNSW.

    uv run python -m scripts.seed 10000
    uv run python -m scripts.benchmark

Compara dos ejes a la vez: latencia y recall. El recall importa porque los dos
índices son APROXIMADOS — la velocidad se paga con aciertos perdidos.
"""

import asyncio
import logging
import statistics
import time

from sqlalchemy import func, select, text

from app.database import async_session, engine
from app.models.note import Note
from app.services.embeddings import embedding_service

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
for _noisy in ("httpx", "sentence_transformers", "transformers"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)
# ERROR y no WARNING: el aviso de HF_TOKEN es nivel WARNING.
logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
logger = logging.getLogger("benchmark")

CONSULTAS = [
    "asynchronous code in modern languages",
    "how to bake bread at home",
    "training for long distance running",
    "database index performance tuning",
    "producing electronic music",
]
TOP_K = 10
REPETICIONES = 20
INDICE = "ix_notes_embedding"


async def buscar(session, vector: list[float], forzar_seq: bool) -> tuple[list, float]:
    """Devuelve (ids del top-K, milisegundos). Solo cronometra el SQL."""
    if forzar_seq:
        # LOCAL: solo para esta transacción. Fuerza el camino exacto, que es la
        # verdad contra la que se mide el recall de los índices.
        await session.execute(text("SET LOCAL enable_indexscan = off"))

    distancia = Note.embedding.cosine_distance(vector)
    stmt = select(Note.id).where(Note.embedding.is_not(None)).order_by(distancia).limit(TOP_K)

    t0 = time.perf_counter()
    filas = (await session.execute(stmt)).scalars().all()
    return list(filas), (time.perf_counter() - t0) * 1000


async def medir(session, vectores, forzar_seq=False) -> tuple[float, float, list[list]]:
    """Corre todas las consultas N veces. Devuelve (mediana, p95, resultados)."""
    tiempos, resultados = [], []
    for vector in vectores:
        # Primera pasada: se guardan los ids (para el recall) y se tira el tiempo,
        # que incluye la caché fría.
        ids, _ = await buscar(session, vector, forzar_seq)
        resultados.append(ids)
        for _ in range(REPETICIONES):
            _, ms = await buscar(session, vector, forzar_seq)
            tiempos.append(ms)

    tiempos.sort()
    p95 = tiempos[int(len(tiempos) * 0.95)]
    return statistics.median(tiempos), p95, resultados


def recall(exactos: list[list], aproximados: list[list]) -> float:
    """Fracción del top-K real que el índice sí encontró."""
    total = sum(len(e) for e in exactos)
    aciertos = sum(len(set(e) & set(a)) for e, a in zip(exactos, aproximados, strict=True))
    return aciertos / total if total else 0.0


async def crear_indice(session, ddl: str) -> float:
    await session.execute(text(f"DROP INDEX IF EXISTS {INDICE}"))
    await session.commit()
    t0 = time.perf_counter()
    await session.execute(text(ddl))
    await session.commit()
    return time.perf_counter() - t0


async def main() -> None:
    await asyncio.to_thread(embedding_service.load)
    vectores = await embedding_service.embed_many(CONSULTAS)

    async with async_session() as session:
        filas = await session.scalar(select(func.count()).select_from(Note))
        if not filas:
            logger.error("Tabla vacía. Corre primero: uv run python -m scripts.seed 10000")
            return

        # Regla de pgvector: lists = filas/1000 hasta 1M. Mínimo 1.
        lists = max(1, filas // 1000)
        logger.info("%d notas, top_k=%d, %d consultas x %d repeticiones",
                    filas, TOP_K, len(CONSULTAS), REPETICIONES)
        logger.info("")

        # 1. Sin índice: la verdad de referencia.
        await session.execute(text(f"DROP INDEX IF EXISTS {INDICE}"))
        await session.commit()
        mediana, p95, exactos = await medir(session, vectores, forzar_seq=True)
        logger.info("%-12s mediana %7.1f ms   p95 %7.1f ms   recall 100.0%%   (exacto)",
                    "Sin índice", mediana, p95)

        # 2. IVFFlat: clusters, escanea probes de ellos.
        construccion = await crear_indice(
            session,
            f"CREATE INDEX {INDICE} ON notes "
            f"USING ivfflat (embedding vector_cosine_ops) WITH (lists = {lists})",
        )
        mediana, p95, aprox = await medir(session, vectores)
        logger.info("%-12s mediana %7.1f ms   p95 %7.1f ms   recall %5.1f%%   (build %.1fs, lists=%d)",
                    "IVFFlat", mediana, p95, recall(exactos, aprox) * 100, construccion, lists)

        # 3. HNSW: grafo por capas. Más lento de construir, más rápido de leer.
        construccion = await crear_indice(
            session,
            f"CREATE INDEX {INDICE} ON notes USING hnsw (embedding vector_cosine_ops)",
        )
        mediana, p95, aprox = await medir(session, vectores)
        logger.info("%-12s mediana %7.1f ms   p95 %7.1f ms   recall %5.1f%%   (build %.1fs)",
                    "HNSW", mediana, p95, recall(exactos, aprox) * 100, construccion)

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
