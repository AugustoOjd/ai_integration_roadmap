from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App configuration. Each field is filled from an env var of the same name."""

    # Default matches docker-compose.yml's postgres service (host=localhost when
    # running the app outside Docker, host=postgres when running inside it —
    # docker-compose overrides this via its own DATABASE_URL env var)
    DATABASE_URL: str = "postgresql+asyncpg://postgres:password@localhost:5432/mini_db"

    # Also read a local .env file if present; ignore any extra/unknown env vars
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


# Instantiated once at import time; every module imports this same `settings` object
settings = Settings()
