from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Config que cambia entre entornos. Cada campo se llena de un env var con
    el mismo nombre."""

    # El puerto debe coincidir con POSTGRES_PORT del .env. Dentro de Docker se
    # sobreescribe a postgres:5432.
    DATABASE_URL: str = "postgresql+asyncpg://postgres:password@localhost:5432/mini_db"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


# Una sola instancia; todos los módulos importan este mismo objeto.
settings = Settings()
