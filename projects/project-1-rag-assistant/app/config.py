from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Literal y no str: un typo como ENVIRONMENT=prod falla al arrancar en vez de
# caer en la rama de desarrollo.
Environment = Literal["development", "staging", "production"]


class Settings(BaseSettings):
    """Config que cambia entre entornos. Cada campo se llena de un env var con
    el mismo nombre."""

    ENVIRONMENT: Environment = "development"

    # Defaults de desarrollo local. En cualquier despliegue vienen del entorno.
    DATABASE_URL: str = "postgresql+asyncpg://postgres:password@localhost:5435/rag_db"
    REDIS_URL: str = "redis://localhost:6380/0"

    # Embeddings en local. Su tamaño de salida es EMBEDDING_DIM.
    #
    # multi-qa y no all-MiniLM: este está entrenado con pares pregunta-respuesta,
    # o sea recuperación asimétrica (query corta contra pasaje largo), que es lo
    # que hace un RAG. all-MiniLM es simétrico y da similitudes mucho más planas.
    # Ambos son de 384 dimensiones, así que la columna no cambia.
    MODEL_NAME: str = "multi-qa-MiniLM-L6-cos-v1"

    # Ingesta. Cambiarlos no rompe la base: obliga a re-trocear desde original_text.
    CHUNK_SIZE: int = 1000
    CHUNK_OVERLAP: int = 200
    MAX_UPLOAD_BYTES: int = 10 * 1024 * 1024

    # Recuperación: cuántos chunks se le pasan al LLM como contexto.
    TOP_K: int = 5

    # Por debajo de esta similitud no se llama al LLM: si nada del corpus se
    # parece a la pregunta, generar solo produce invención.
    MIN_SIMILARITY: float = 0.25

    # Generación. max_tokens es el tope de coste por petición.
    MAX_RESPONSE_TOKENS: int = 700
    # Bajo a propósito: son respuestas factuales sobre un documento.
    TEMPERATURE: float = 0.2

    # Historial que se acepta del cliente, en turnos y en caracteres.
    MAX_HISTORY_TURNS: int = 6
    MAX_HISTORY_CHARS: int = 4000

    # TTL del caché de respuestas. Corto a propósito: si cambia el corpus, las
    # respuestas viejas caducan solas.
    CACHE_TTL_SECONDS: int = 3600

    # Proveedor del LLM, por API compatible con OpenAI.
    LLM_BASE_URL: str = "https://api.groq.com/openai/v1"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "llama-3.3-70b-versatile"

    # Autenticación de esta API. Ver app/dependencies.py.
    API_KEY: str = ""

    # Límite del endpoint público: peticiones por IP y ventana.
    RATE_LIMIT_REQUESTS: int = 30
    RATE_LIMIT_WINDOW_SECONDS: int = 60

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def is_dev(self) -> bool:
        return self.ENVIRONMENT == "development"

    @model_validator(mode="after")
    def _exigir_secretos_fuera_de_dev(self) -> "Settings":
        """Corre al construir Settings, o sea al importar este módulo."""
        if self.is_dev:
            return self

        faltantes = [
            nombre for nombre in ("API_KEY", "LLM_API_KEY") if not getattr(self, nombre)
        ]
        if faltantes:
            raise ValueError(
                f"ENVIRONMENT={self.ENVIRONMENT} requiere: {', '.join(faltantes)}"
            )
        return self


# Una sola instancia; todos los módulos importan este mismo objeto.
settings = Settings()


# No es un Setting a propósito: va al DDL (`embedding vector(384)`), que corre al
# arrancar, antes de cargar el modelo. Y no puede variar por entorno: la columna
# queda fija en el CREATE TABLE.
EMBEDDING_DIM = 384

# Vectores normalizados y sin normalizar en la misma tabla dan distancias sin
# sentido al compararlos entre sí.
NORMALIZE_EMBEDDINGS = True
