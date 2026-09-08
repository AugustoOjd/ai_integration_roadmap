from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Todo lo que cambia entre entornos (local, Docker, prod).

    Cada campo se llena desde una variable de entorno con el mismo nombre; si no
    existe, usa el default de acá. Ese default apunta a localhost porque es el
    caso de desarrollo; en Docker, compose pisa las tres URLs con el host `redis`.
    """

    # ------------------------------------------------------------------ Celery

    # Broker = la cola de entrada. La API hace LPUSH acá, el worker hace BRPOP
    # esperando trabajo.
    CELERY_BROKER_URL: str = "redis://localhost:6381/0"

    # Backend = el almacén de salida: guarda el valor de retorno (y el estado)
    # indexado por task_id. DB distinta para poder limpiar una sin tocar la otra.
    CELERY_RESULT_BACKEND: str = "redis://localhost:6381/1"

    # TTL de los resultados en Redis. Sin esto cada tarea deja una key para
    # siempre y Redis crece sin techo.
    #
    # Este número es EXACTAMENTE la razón por la que existe la dead letter queue
    # de la Fase 3: pasada una hora, el FAILURE de una tarea desaparece. Si no lo
    # guardaste en otro lado, el fallo no existió.
    CELERY_RESULT_EXPIRES: int = 3600

    # ------------------------------------------------- Dead letter queue (F3)

    # DB aparte de la cola y de los resultados: lo que muere acá es lo que menos
    # querés perder, así que no comparte destino con nada que se limpie seguido.
    DEAD_LETTER_URL: str = "redis://localhost:6381/2"

    # La DLQ es una lista de Redis; esta es su key. Fija, pero configurable para
    # poder aislarla en los tests sin tocar la real.
    DEAD_LETTER_KEY: str = "dlq:tasks"

    # Cota superior de la lista. Una DLQ sin techo es una fuga de memoria lenta:
    # si algo falla en bucle, llena Redis. Al superar el límite se descartan las
    # entradas más viejas (las nuevas son las que estás debuggeando).
    DEAD_LETTER_MAX: int = 1000

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


# Una sola instancia, importada por todos los módulos. Se construye al importar:
# si falta una env var obligatoria, el proceso muere al arrancar y no a mitad de
# una request.
settings = Settings()
