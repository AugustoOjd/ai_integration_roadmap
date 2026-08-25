from pydantic import BaseModel, Field

from app.config import settings


class SearchRequest(BaseModel):
    """Body de POST /search/query."""

    # min_length=1: embeber "" da un vector sin significado.
    query: str = Field(min_length=1, max_length=2000)
    # le=20 acota el LIMIT: el cliente no deberia poder pedir la tabla entera.
    top_k: int = Field(default=settings.TOP_K, ge=1, le=20)


class SearchResult(BaseModel):
    """Un chunk recuperado, con su procedencia."""

    source: str
    page: int | None
    section: str | None
    chunk: str

    # No es una columna: la calcula Postgres como 1 - (embedding <=> query).
    # El rango es [-1, 1] porque la distancia coseno va de 0 a 2.
    similarity: float = Field(ge=-1.0, le=1.0)


class SearchResponse(BaseModel):
    """Se devuelve la query junto a los resultados para que el cliente pueda
    correlacionar respuestas si lanza varias en paralelo."""

    query: str
    results: list[SearchResult]
