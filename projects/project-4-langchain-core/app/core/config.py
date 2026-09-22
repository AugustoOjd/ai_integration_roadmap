"""Lo que cambia entre entornos, leído del entorno y del .env."""

import os
from pathlib import Path

from pydantic import PostgresDsn, RedisDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

RAIZ = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Los campos sin default son requisitos: si faltan, falla al importar."""

    VOYAGE_API_KEY: SecretStr
    ANTHROPIC_API_KEY: SecretStr

    # "<provider>:<modelo>". Lo único que se toca en el swap test de la fase 4.
    EMBEDDING_MODEL: str = "voyageai:voyage-3.5-lite"
    CHAT_MODEL: str = "anthropic:claude-haiku-4-5"

    # ⚠️ psycopg y no asyncpg: langchain-postgres no soporta asyncpg.
    DATABASE_URL: PostgresDsn = "postgresql+psycopg://nordix:nordix@localhost:5436/nordix"  # type: ignore[assignment]

    REDIS_URL: RedisDsn = "redis://localhost:6381/0"  # type: ignore[assignment]

    # El splitter toma estos números; no los elige. Cambiarlos es un
    # experimento contra el set de preguntas, no una preferencia.
    CHUNK_SIZE: int = 1000
    CHUNK_OVERLAP: int = 200

    # Cuántos chunks recupera el retriever por consulta.
    RETRIEVER_K: int = 4

    CORPUS_DIR: Path = RAIZ / "corpus"
    PREGUNTAS: Path = RAIZ / "evals" / "preguntas.json"

    # Nombre de la colección en PGVector. Cambiarlo al probar otro modelo de
    # embeddings evita mezclar vectores de espacios distintos en la misma tabla.
    COLLECTION: str = "nordix_voyage_3_5_lite"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()  # type: ignore[call-arg]

# El .env lo lee pydantic-settings a este objeto, no a os.environ. Los clientes
# de LangChain leen os.environ, así que las keys hay que exportarlas.
# setdefault: una variable ya puesta en la shell gana.
for _campo in ("VOYAGE_API_KEY", "ANTHROPIC_API_KEY"):
    os.environ.setdefault(_campo, getattr(settings, _campo).get_secret_value())
