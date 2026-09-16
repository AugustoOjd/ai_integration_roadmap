from pydantic import PostgresDsn, RedisDsn, SecretStr
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
    # Cola
    # ------------------------------------------------------------------

    # El broker: dónde se encolan las tareas. Bases distintas de Redis (`/0` y
    # `/1`) para que un `FLUSHDB` sobre los resultados no se lleve la cola.
    CELERY_BROKER_URL: RedisDsn = "redis://localhost:6379/0"  # type: ignore[assignment]

    # Dónde Celery guarda el estado y el valor de retorno de cada tarea. Es un
    # detalle de transporte, no la fuente de verdad del negocio — eso es la tabla
    # `tasks`.
    CELERY_RESULT_BACKEND: RedisDsn = "redis://localhost:6379/1"  # type: ignore[assignment]

    # La dead letter queue. Va en una tercera base: es lo ÚNICO de Redis que no
    # querés perder en un FLUSHDB, porque es el registro de lo que se perdió.
    DEAD_LETTER_URL: RedisDsn = "redis://localhost:6379/2"  # type: ignore[assignment]
    DEAD_LETTER_KEY: str = "dlq:agent"

    # Techo de entradas. Una DLQ sin tope es una fuga de memoria lenta: una tarea
    # que falla en bucle la llena sola.
    DEAD_LETTER_MAX: int = 500

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
