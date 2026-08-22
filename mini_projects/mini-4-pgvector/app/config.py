from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Config que cambia entre entornos. Cada campo se llena de un env var con
    el mismo nombre."""

    # 5433 = lado host del mapeo de docker-compose (5432 lo usan mini-1/mini-2).
    # Dentro de Docker se sobreescribe a postgres:5432.
    DATABASE_URL: str = "postgresql+asyncpg://postgres:password@localhost:5433/mini_db"

    # Mismo modelo que mini-3. Su tamaño de salida es EMBEDDING_DIM.
    MODEL_NAME: str = "all-MiniLM-L6-v2"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


# Una sola instancia; todos los módulos importan este mismo objeto.
settings = Settings()


# No es un Setting a propósito: va al DDL (`embedding vector(384)`), que corre al
# arrancar, antes de cargar el modelo. Y no puede variar por entorno: la columna
# queda fija en el CREATE TABLE.
# Un chequeo al arranque lo compara contra el modelo real para fallar temprano.
EMBEDDING_DIM = 384

# Vectores normalizados y sin normalizar en la misma tabla dan distancias sin
# sentido al compararlos entre sí.
NORMALIZE_EMBEDDINGS = True
