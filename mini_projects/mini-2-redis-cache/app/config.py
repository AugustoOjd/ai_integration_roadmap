from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App configuration. Each field is filled from an env var of the same name."""

    # Matches docker-compose.yml's postgres service (host=localhost outside Docker,
    # host=postgres inside it — docker-compose overrides this via its own env var)
    DATABASE_URL: str = "postgresql+asyncpg://postgres:password@localhost:5432/mini_db"

    # Same idea for Redis: /0 selects database index 0 (Redis's default)
    REDIS_URL: str = "redis://localhost:6379/0"

    # Also read a local .env file if present; ignore any extra/unknown env vars
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


# Instantiated once at import time; every module imports this same `settings` object
settings = Settings()
