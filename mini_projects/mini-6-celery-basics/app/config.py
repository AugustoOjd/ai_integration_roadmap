from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Config que cambia entre entornos. Cada campo se llena de un env var con
    el mismo nombre."""

    # Broker = la cola de entrada. El worker hace BRPOP aquí esperando tareas.
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"

    # Backend = donde se guarda el resultado. DB distinta (/1) para poder
    # limpiar la cola con FLUSHDB sin borrar resultados, y al revés.
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"

    # TTL de los resultados en Redis. Sin esto, cada tarea deja una key para
    # siempre y Redis crece sin techo. 1h basta para consultar el status.
    CELERY_RESULT_EXPIRES: int = 3600

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


# Una sola instancia; todos los módulos importan este mismo objeto.
settings = Settings()
