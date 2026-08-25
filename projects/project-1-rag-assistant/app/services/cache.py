import hashlib
import logging

import redis.asyncio as redis

from app.config import settings

logger = logging.getLogger(__name__)

# decode_responses=True: Redis devuelve str en vez de bytes, así no hay que
# hacer .decode() en cada lectura.
# El pool se crea perezosamente; el lifespan lo cierra al apagar.
redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)

# Contador que se incrementa al cambiar el corpus. Va dentro de la clave, así
# que subirlo deja inalcanzables todas las respuestas viejas de golpe, sin
# recorrer el keyspace. Las huérfanas caducan solas por TTL.
VERSION_KEY = "corpus:version"


async def _version() -> str:
    return await redis_client.get(VERSION_KEY) or "0"


async def bump_corpus_version() -> None:
    """Invalida todo el caché de respuestas. La llaman upload y delete."""
    nueva = await redis_client.incr(VERSION_KEY)
    logger.info("CACHE INVALIDATE -> corpus v%s", nueva)


def _hash(query: str, top_k: int) -> str:
    """Identifica la consulta.

    Entra el modelo porque respuestas de modelos distintos no son
    intercambiables, y top_k porque cambia el contexto y por tanto la respuesta.
    La query se normaliza para que "Que es un legend?" y "  que es un LEGEND? "
    compartan entrada.
    """
    material = f"{settings.LLM_MODEL}|{top_k}|{' '.join(query.lower().split())}"
    return hashlib.sha256(material.encode()).hexdigest()


async def get_answer(query: str, top_k: int) -> str | None:
    clave = f"answer:v{await _version()}:{_hash(query, top_k)}"
    return await redis_client.get(clave)


async def set_answer(query: str, top_k: int, payload: str) -> None:
    clave = f"answer:v{await _version()}:{_hash(query, top_k)}"
    await redis_client.setex(clave, settings.CACHE_TTL_SECONDS, payload)
