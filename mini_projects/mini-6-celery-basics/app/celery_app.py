from celery import Celery

from app.config import settings

# El primer arg es el nombre de la app: prefija el nombre de las tareas
# ("app.tasks.foo") y es lo que apunta `celery -A app.celery_app`.
celery_app = Celery(
    "mini6",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    # El worker solo conoce las tareas de los módulos que importa. String, no
    # import: se resuelve al arrancar y evita el ciclo con app.tasks.
    include=["app.tasks"],
)

celery_app.conf.update(
    # JSON, no pickle. pickle ejecuta código al deserializar: quien pueda
    # escribir en Redis ejecuta en el worker.
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    result_expires=settings.CELERY_RESULT_EXPIRES,
    # Sin esto el estado STARTED no existe: la tarea salta de PENDING a SUCCESS
    # y no puedes distinguir "en cola" de "ejecutándose".
    task_track_started=True,
    # ack al TERMINAR, no al recibir. Si el worker muere a media tarea, el
    # mensaje sigue en la cola y otro lo retoma. Exige tareas idempotentes.
    task_acks_late=True,
    # Cada worker reserva 1 tarea a la vez en vez de acaparar un lote. Con
    # tareas de duración desigual evita que un worker quede con la cola llena
    # mientras otro está libre.
    worker_prefetch_multiplier=1,
)
