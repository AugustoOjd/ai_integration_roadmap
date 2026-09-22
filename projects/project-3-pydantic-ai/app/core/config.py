"""Lo que cambia entre entornos, leído del entorno y del .env."""

import os

from pydantic import PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Los campos sin default son requisitos: si faltan, falla al importar."""

    # SecretStr no encripta: hace que el repr() sea '**********'.
    ANTHROPIC_API_KEY: SecretStr

    # Opcionales: sólo hacen falta si AGENT_MODEL apunta a ese provider.
    OPENAI_API_KEY: SecretStr | None = None
    GEMINI_API_KEY: SecretStr | None = None
    GROQ_API_KEY: SecretStr | None = None

    # Formato "<provider>:<modelo>".
    AGENT_MODEL: str = "anthropic:claude-haiku-4-5"

    # `+psycopg` nombra el driver; psycopg3 corre sincrónico y async con el mismo
    # paquete. PostgresDsn valida la forma al arrancar.
    DATABASE_URL: PostgresDsn = "postgresql+psycopg://triage:triage@localhost:5433/triage"  # type: ignore[assignment]

    # Imprime todo el SQL que emite SQLAlchemy.
    DB_ECHO: bool = False

    # ------------------------------------------------------------------
    # Instrumentación
    # ------------------------------------------------------------------

    LOGFIRE: bool = False

    # Con token las spans van a la UI de Logfire; sin token, a la consola.
    # Lo lee logfire del entorno, igual que las keys de los providers.
    LOGFIRE_TOKEN: SecretStr | None = None

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


# type: ignore: falso positivo de pydantic-settings, no sabe que los campos sin
# default los llena el entorno.
settings = Settings()  # type: ignore[call-arg]

# El .env lo lee pydantic-settings a este objeto, no a os.environ. Cada SDK mira
# os.environ cuando Pydantic AI resuelve el string "<provider>:...", así que las
# keys hay que exportarlas o no las encuentra.
# setdefault y no asignación: una variable ya puesta en la shell gana.
for _campo in (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "GROQ_API_KEY",
    "LOGFIRE_TOKEN",
):
    _valor: SecretStr | None = getattr(settings, _campo)
    if _valor is not None:
        os.environ.setdefault(_campo, _valor.get_secret_value())
