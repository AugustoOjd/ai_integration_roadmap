"""Carga N notas sintéticas con su embedding.

    uv run python -m scripts.seed 10000

Con -m (y no `python scripts/seed.py`) el cwd entra en sys.path y `import app`
funciona; ejecutado por ruta, Python solo añade scripts/.

Sin volumen, el benchmark no dice nada: con pocas filas Postgres siempre elige
Seq Scan porque leer la tabla entera es más barato que abrir un índice.
"""

import asyncio
import logging
import random
import sys
import time

from sqlalchemy import delete, insert, text

from app.database import async_session, engine, init_db
from app.models.note import Note
from app.services.embeddings import embedding_service

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
for _noisy in ("httpx", "sentence_transformers", "transformers"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)
# ERROR y no WARNING: el aviso de HF_TOKEN es nivel WARNING.
logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
logger = logging.getLogger("seed")

# Texto compuesto por combinación, no aleatorio: los vectores tienen que
# agruparse por tema para que el recall del benchmark signifique algo.
# Cada tema aporta sujetos, aspectos y detalles; ver COMBINACIONES abajo.
TEMAS = {
    "programming": (
        ["Python", "JavaScript", "Rust", "Go", "TypeScript", "Java", "Elixir", "Kotlin"],
        ["async programming", "memory management", "error handling", "unit testing",
         "type systems", "dependency injection", "code review", "refactoring"],
        ["The compiler catches most of it early.", "Profiling changed my assumptions.",
         "Readability beat cleverness here.", "The stack traces were finally useful.",
         "Static analysis found three real bugs.", "Concurrency made this subtle.",
         "The migration took two sprints.", "Benchmarks contradicted the docs.",
         "Legacy code forced a compromise.", "The team disagreed on style.",
         "Test coverage hid a gap.", "The API surface kept growing."],
    ),
    "cooking": (
        ["sourdough bread", "pasta carbonara", "ramen broth", "chocolate cake",
         "roast chicken", "risotto", "tacos al pastor", "miso soup"],
        ["fermentation", "knife skills", "oven temperature", "ingredient ratios",
         "resting time", "seasoning balance", "texture control", "plating"],
        ["Humidity changed everything.", "The starter needed another day.",
         "Salt late, not early.", "Room temperature matters more than expected.",
         "The crust finally cracked properly.", "Cheap pans burn the edges.",
         "Weighing beats measuring cups.", "The sauce split on reheating.",
         "Resting doubled the juiciness.", "Fresh herbs at the end only.",
         "Overmixing ruined the crumb.", "A hotter oven fixed the base."],
    ),
    "sports": (
        ["marathon running", "swimming", "cycling", "rock climbing",
         "rowing", "trail running", "triathlon", "powerlifting"],
        ["training plans", "injury recovery", "nutrition", "endurance",
         "pacing", "sleep quality", "mobility work", "race strategy"],
        ["Heart rate zones told a different story.", "The taper felt too easy.",
         "Recovery weeks are not optional.", "Hills exposed the weak base.",
         "Hydration was the limiting factor.", "The shoes changed my cadence.",
         "Cold weather shifted everything.", "A physio caught the imbalance.",
         "Negative splits worked once.", "Cross training saved the season.",
         "The final kilometre was mental.", "Fuelling early prevented the wall."],
    ),
    "databases": (
        ["PostgreSQL", "Redis", "MongoDB", "SQLite",
         "ClickHouse", "Cassandra", "DuckDB", "MySQL"],
        ["indexing strategies", "replication", "query planning", "transactions",
         "connection pooling", "partitioning", "vacuum tuning", "schema migrations"],
        ["The planner ignored the index.", "Stale statistics caused the regression.",
         "Locks piled up under load.", "The read replica lagged badly.",
         "Partitioning cut the scan in half.", "A composite index solved it.",
         "The pool size was the bottleneck.", "EXPLAIN ANALYZE told the truth.",
         "Bloat grew faster than expected.", "The migration needed a backfill.",
         "Isolation level changed the results.", "Batching removed most round trips."],
    ),
    "music": (
        ["jazz improvisation", "classical piano", "electronic production",
         "flamenco guitar", "choral arrangement", "film scoring", "drumming", "songwriting"],
        ["chord progressions", "rhythm", "mixing", "sound design",
         "dynamics", "voice leading", "modulation", "arrangement"],
        ["The room changed the recording.", "Silence did more than the fill.",
         "Sidechaining cleaned up the low end.", "Practising slowly fixed the passage.",
         "The bridge needed a key change.", "Analog warmth was mostly placebo.",
         "Reference tracks exposed the mix.", "The tempo drifted on purpose.",
         "Layering thinned the character.", "One microphone beat four.",
         "The chorus arrived too late.", "Mono compatibility broke the width."],
    ),
}

PLANTILLAS = [
    "Notes on {a}: understanding {b} in practice.",
    "A short guide to {b} when working with {a}.",
    "Why {b} matters if you care about {a}.",
    "Common mistakes with {a} and how {b} helps.",
    "Deep dive into {a}, focusing on {b}.",
    "What I learned about {b} while studying {a}.",
    "Revisiting {a} after months away, especially {b}.",
    "Field notes: {a} and the role of {b}.",
]


def generar(n: int) -> list[dict]:
    """n notas únicas repartidas entre los temas.

    El texto se compone de 4 ejes (sujeto, aspecto, plantilla, 2 detalles), lo
    que da ~1.5M combinaciones por tema. Sin esa variedad los embeddings salen
    casi duplicados y el recall del benchmark da 100% falso.
    """
    random.seed(42)  # corridas reproducibles: el benchmark compara entre sí

    vistas: set[tuple] = set()
    notas: list[dict] = []
    temas = list(TEMAS)

    while len(notas) < n:
        # Rotar por tema mantiene los clusters balanceados.
        tema = temas[len(notas) % len(temas)]
        sujetos, aspectos, detalles = TEMAS[tema]

        a, b = random.choice(sujetos), random.choice(aspectos)
        plantilla = random.choice(PLANTILLAS)
        d1, d2 = random.sample(detalles, 2)

        clave = (a, b, plantilla, d1, d2)
        if clave in vistas:
            continue
        vistas.add(clave)

        notas.append(
            {
                "title": f"{a} — {b}"[:200],
                "content": f"{plantilla.format(a=a, b=b)} {d1} {d2} Filed under {tema}.",
            }
        )
    return notas


async def main(n: int) -> None:
    await init_db()
    await asyncio.to_thread(embedding_service.load)

    notas = generar(n)
    logger.info("Generadas %d notas sobre %d temas", len(notas), len(TEMAS))

    t0 = time.perf_counter()
    vectores = await embedding_service.embed_many([f"{x['title']}\n{x['content']}" for x in notas])
    logger.info("Embeddings: %.1fs (%.1f notas/s)", time.perf_counter() - t0, n / (time.perf_counter() - t0))

    filas = [{**nota, "embedding": vec} for nota, vec in zip(notas, vectores, strict=True)]

    async with async_session() as session:
        # Tabla limpia: mezclar corridas falsearía el conteo del benchmark.
        await session.execute(delete(Note))

        t0 = time.perf_counter()
        # insert() en bloque, no db.add() por fila: un round-trip por lote en vez
        # de N. Lotes de 500 para no armar una sentencia gigantesca.
        for i in range(0, len(filas), 500):
            await session.execute(insert(Note), filas[i : i + 500])
        await session.commit()
        logger.info("INSERT: %.1fs", time.perf_counter() - t0)

        # Sin ANALYZE el planificador sigue estimando a ojo (recuerda rows=149).
        await session.execute(text("ANALYZE notes"))
        await session.commit()

    await engine.dispose()
    logger.info("Listo. Ahora: uv run python -m scripts.benchmark")


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 10_000))
