from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Config que cambia entre entornos. Cada campo se llena de un env var con
    el mismo nombre."""

    # 5434 es el lado HOST del mapeo de docker-compose (5432 lo usan mini-1/2,
    # 5433 mini-4). Dentro de Docker se sobreescribe a postgres:5432.
    DATABASE_URL: str = "postgresql+asyncpg://postgres:password@localhost:5434/mini_db"

    # Sí son Settings, al revés que EMBEDDING_DIM en mini-4: cambiarlos no rompe
    # nada en la base, solo hay que re-trocear desde original_text.
    CHUNK_SIZE: int = 1000
    CHUNK_OVERLAP: int = 200

    # 10MB. Sin límite, un archivo gigante se carga entero en RAM.
    MAX_UPLOAD_BYTES: int = 10 * 1024 * 1024

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


# Una sola instancia; todos los módulos importan este mismo objeto.
settings = Settings()
