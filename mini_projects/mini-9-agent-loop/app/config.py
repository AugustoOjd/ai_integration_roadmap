from pydantic import PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Todo lo que cambia entre entornos (local, CI, prod).

    Cada campo se llena desde una variable de entorno con el mismo nombre. Los
    que tienen default son preferencias; los que NO tienen default son
    requisitos: si faltan, Pydantic tira ValidationError al importar este módulo
    y el proceso no arranca.

    Respecto del mini 8 hay dos grupos nuevos: la base (donde ahora vive el
    estado del agente) y el presupuesto (porque ahora las conversaciones duran
    y cuestan).
    """

    # ------------------------------------------------------------------
    # Modelo — idéntico al mini 8
    # ------------------------------------------------------------------

    # `SecretStr` no encripta nada: lo único que hace es que su `repr()` sea
    # `SecretStr('**********')`. Eso importa más de lo que parece, porque los
    # objetos de settings terminan impresos sin querer en trazas de excepciones
    # y logs de debug. Para usarla hay que pedirla con `.get_secret_value()`, y
    # esa fricción es el punto: filtrarla pasa a ser una decisión, no un
    # descuido.
    #
    # Sin default a propósito: si falta, el proceso no arranca. Un arranque que
    # falla es mucho más barato de diagnosticar que una app viva que devuelve
    # 401 en el primer request de un usuario real.
    ANTHROPIC_API_KEY: SecretStr

    # Haiku 4.5: barato ($1/$5 por millón de tokens in/out) y rápido, que es lo
    # que importa cuando cada request son VARIAS llamadas al modelo.
    #
    # En este mini su límite de contexto (200K, no 1M) deja de ser un dato
    # curioso y pasa a ser el motor de la Fase 8: con el historial persistido,
    # una sesión larga se acerca a ese techo de verdad.
    ANTHROPIC_MODEL: str = "claude-haiku-4-5"

    # Techo de tokens GENERADOS por respuesta. No es un presupuesto de costo: es
    # un cuchillo. Si el modelo lo toca, la respuesta se corta donde estuviera y
    # `stop_reason` vuelve como "max_tokens".
    #
    # Sirve además para la Fase 7: el costo del OUTPUT no se puede estimar de
    # antemano, así que este número es la única cota superior que tenés sobre él.
    ANTHROPIC_MAX_TOKENS: int = 4096

    # Cuánto esperamos UNA llamada al modelo antes de abandonarla. El default
    # del SDK son 10 minutos, pensado para trabajos largos; detrás de un
    # endpoint HTTP eso es un worker de uvicorn ocupado 10 minutos.
    ANTHROPIC_TIMEOUT: float = 30.0

    # ------------------------------------------------------------------
    # Base de datos — nuevo en este mini
    # ------------------------------------------------------------------

    # La URL nombra al driver, no sólo al motor: `postgresql+asyncpg` le dice a
    # SQLAlchemy que use asyncpg. Si dice sólo `postgresql://`, SQLAlchemy elige
    # el driver sincrónico (psycopg) y `create_async_engine` falla con un error
    # poco obvio. Cambiar de driver es cambiar el .env, no el código.
    #
    # `PostgresDsn` valida la forma al arrancar (esquema, host, puerto) en vez
    # de dejarte descubrir el typo en el primer request. Ojo: el password viaja
    # adentro de la URL, así que este valor no se loguea nunca.
    #
    # El default va como str y Pydantic lo valida y lo convierte al tipo: es la
    # forma de escribir un default de URL que funciona igual en cualquier
    # versión de Pydantic v2.
    DATABASE_URL: PostgresDsn = "postgresql+asyncpg://mini9:mini9@localhost:5432/mini9"  # type: ignore[assignment]

    # Imprime cada sentencia SQL que emite SQLAlchemy. Apagado por default
    # porque es ruidosísimo, pero prenderlo un rato en la Fase 1 es la forma más
    # rápida de ver que un `load_history` está haciendo N+1 queries o que un
    # turno se está commiteando en pedazos.
    DB_ECHO: bool = False

    # ------------------------------------------------------------------
    # Agente — nuevo en este mini
    # ------------------------------------------------------------------

    # Tope de vueltas del loop. Viene del mini 8 (era una constante en
    # `agent.py`) y sube a config porque acá convive con el otro tope, el de
    # tokens: son dos límites distintos y hacen falta los dos.
    #   - max_iterations protege contra el loop infinito (modelo confundido).
    #   - budget_tokens protege contra el gasto (historial grande).
    # Cinco iteraciones pueden ser centavos o pueden ser caras; sólo el segundo
    # tope sabe la diferencia.
    AGENT_MAX_ITERATIONS: int = 8

    # Presupuesto inicial de una sesión nueva, en tokens de INPUT acumulados.
    # Es un default de producto, no una constante técnica: cada sesión guarda el
    # suyo en la base (Fase 0) y podría venir del plan que tiene contratado el
    # usuario.
    DEFAULT_BUDGET_TOKENS: int = 50_000

    # Precios de Haiku 4.5, en dólares por millón de tokens.
    #
    # Van como settings y no hardcodeados en `budget.py` porque los precios
    # cambian, y cuando cambian querés corregir el número sin un deploy. Son
    # dos y no uno porque entrada y salida cuestan distinto — ésa es también la
    # razón por la que la tabla `sessions` lleva dos contadores separados.
    PRECIO_INPUT_USD_POR_MTOK: float = 1.0
    PRECIO_OUTPUT_USD_POR_MTOK: float = 5.0

    # Techo de contexto por request, en tokens de entrada (Fase 8).
    #
    # Haiku 4.5 tiene 200K de ventana. Este número va deliberadamente por
    # debajo, y no pegado: el límite del modelo incluye lo que él GENERA, y
    # llegar justo significa que el request entra pero la respuesta se corta por
    # falta de lugar. El margen también absorbe el error de estimación.
    #
    # Es un tope distinto del presupuesto aunque se midan en la misma unidad:
    # el presupuesto es de plata y acumulativo por sesión; éste es físico y por
    # request. El loop usa el menor de los dos.
    CONTEXT_MAX_INPUT_TOKENS: int = 150_000

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


# Una sola instancia, importada por todos los módulos. Se construye al importar:
# si falta la API key o la URL está mal escrita, el proceso muere al arrancar y
# no a mitad de una request.
#
# El `type: ignore` es por un falso positivo conocido de pydantic-settings: el
# type checker ve un campo sin default y cree que `Settings()` necesita el
# argumento, porque no sabe que los valores los llena el entorno / el .env. La
# alternativa —ponerle un default al campo para callar al editor— cambiaría el
# comportamiento en runtime, que es justamente lo que no queremos.
settings = Settings()  # type: ignore[call-arg]
