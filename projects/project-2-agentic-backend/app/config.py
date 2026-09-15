from pydantic import PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Todo lo que cambia entre entornos, leído del entorno y del .env.

    Los campos con default son preferencias; los que no tienen default son
    requisitos: si faltan, Pydantic tira ValidationError al importar y el
    proceso no arranca.
    """

    # ------------------------------------------------------------------
    # Modelo
    # ------------------------------------------------------------------

    # SecretStr no encripta: hace que el repr() sea '**********', para que no se
    # filtre en trazas ni logs. Se lee con .get_secret_value().
    ANTHROPIC_API_KEY: SecretStr

    ANTHROPIC_MODEL: str = "claude-haiku-4-5"

    # Techo de tokens GENERADOS por respuesta. Si lo toca, la respuesta se corta
    # y stop_reason vuelve "max_tokens".
    ANTHROPIC_MAX_TOKENS: int = 4096

    # Timeout de UNA llamada al modelo. El default del SDK son 10 minutos, que
    # detrás de un worker con acks_late significa trabajo duplicado.
    ANTHROPIC_TIMEOUT: float = 30.0

    # ------------------------------------------------------------------
    # Base de datos
    # ------------------------------------------------------------------

    # El `+psycopg` nombra el driver y es sincrónico, porque las tareas de Celery
    # son funciones sincrónicas: un ORM async adentro obliga a un event loop por
    # tarea y deja el pool con conexiones atadas a un loop muerto.
    # PostgresDsn valida la forma al arrancar en vez de fallar en el primer query.
    DATABASE_URL: PostgresDsn = "postgresql+psycopg://agentic:agentic@localhost:5432/agentic_backend"  # type: ignore[assignment]

    # Imprime todo el SQL. Ruidoso, pero es la forma más rápida de ver un N+1 o
    # un turno commiteándose en pedazos.
    DB_ECHO: bool = False

    # ------------------------------------------------------------------
    # Agente
    # ------------------------------------------------------------------

    # Tope de vueltas: protege del loop infinito. No protege del gasto — eso es
    # el presupuesto, y hacen falta los dos.
    AGENT_MAX_ITERATIONS: int = 8

    # Presupuesto por defecto, en tokens de input acumulados.
    DEFAULT_BUDGET_TOKENS: int = 50_000

    # Dólares por millón de tokens. Dos números porque input y output cuestan
    # distinto.
    PRECIO_INPUT_USD_POR_MTOK: float = 1.0
    PRECIO_OUTPUT_USD_POR_MTOK: float = 5.0

    # Techo de contexto por request. Va por debajo de los 200K de la ventana
    # porque ese límite incluye lo que el modelo genera.
    CONTEXT_MAX_INPUT_TOKENS: int = 150_000

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


# Una sola instancia, construida al importar: una config inválida mata el
# proceso al arrancar en vez de fallar en el primer request o en la primera tarea.
# El type: ignore es un falso positivo de pydantic-settings — el checker no sabe
# que los campos sin default los llena el entorno.
settings = Settings()  # type: ignore[call-arg]
