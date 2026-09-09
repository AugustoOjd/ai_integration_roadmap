from celery import Celery

from app.config import settings

# El primer argumento es el nombre de la app: prefija el nombre de las tareas
# ("app.tasks.foo") y es lo que resuelve `celery -A app.celery_app`.
#
celery_app = Celery(
    "mini7",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    # El worker NO descubre tareas solo: registra únicamente las de los módulos
    # que importa. Sin esta línea, todo lo que encoles muere en el worker con
    # "Received unregistered task: tasks.flaky".
    #
    # Va como string y no como import para que se resuelva al arrancar el
    # worker: importar app.tasks acá crearía un ciclo, porque app/tasks.py
    # importa este mismo módulo para usar el decorador.
    include=["app.tasks"],
)

celery_app.conf.update(
    # ------------------------------------------------------- Serialización
    # JSON, no pickle. pickle ejecuta código arbitrario al deserializar: quien
    # pueda escribir en Redis ejecuta en el worker.
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    # ------------------------------------------------------------ Resultados
    result_expires=settings.CELERY_RESULT_EXPIRES,
    # Sin esto el estado STARTED no existe: la tarea salta de PENDING a SUCCESS
    # y no podés distinguir "en cola" de "ejecutándose".
    task_track_started=True,
    # Guarda TAMBIÉN el nombre de la tarea, sus args y qué worker la ejecutó,
    # no solo el valor de retorno. Es lo que permite que un endpoint de
    # monitoreo diga "el task abc-123 era `procesar_pdf(42)`" en vez de un id
    # pelado. Cuesta unos bytes por resultado y vale cada uno cuando debuggeás.
    result_extended=True,
    # ------------------------------------------------------------- Entrega
    # ack al TERMINAR, no al recibir. Si el worker muere a media tarea, el
    # mensaje sigue en la cola y otro lo retoma. Exige tareas idempotentes:
    # una tarea puede ejecutarse dos veces.
    task_acks_late=True,
    # Cada worker reserva 1 tarea a la vez en vez de acaparar un lote. Con
    # tareas de duración desigual evita que uno quede con la cola llena
    # mientras otro está libre. Además hace que `reserved()` (Fase 5) sea
    # legible: si prefetchea 40, ver esa lista no te dice nada útil.
    worker_prefetch_multiplier=1,
    # Si el proceso hijo muere de golpe (OOM kill, SIGKILL), ¿reencolamos?
    # False = la tarea se marca FAILURE con WorkerLostError.
    # True  = vuelve a la cola... y si la mató su propio consumo de memoria,
    #         vuelve a morir, para siempre. Un bucle infinito silencioso.
    # False es el default y la opción sensata: que falle visible y quede en la
    # dead letter queue (Fase 3), que para eso está.
    task_reject_on_worker_lost=False,
    # ---------------------------------------------------------- Time limits
    # Una tarea colgada (un `requests.get` sin timeout contra un server que no
    # responde) ocupa su slot del worker PARA SIEMPRE. Con concurrencia 2, dos
    # tareas colgadas = worker muerto sin un solo error en el log.
    #
    # soft: levanta SoftTimeLimitExceeded DENTRO de la tarea → se puede atrapar,
    #       hacer cleanup y decidir si reintentar.
    # hard: mata el proceso hijo sin preguntar. Es la red de seguridad de la red
    #       de seguridad; siempre mayor que el soft.
    task_soft_time_limit=300,
    task_time_limit=360,
    # -------------------------------------------------------------- Eventos
    # El worker emite eventos (task-started, task-succeeded...) al broker. No lo
    # usamos en este mini —vamos por `inspect()` en la Fase 5, que es pull— pero
    # es lo que consumen Flower y cualquier dashboard en tiempo real. Apagado
    # por default; encenderlo después no es trivial de recordar.
    worker_send_task_events=True,
    task_send_sent_event=True,
    # -------------------------------------------------------------- Arranque
    # Si Redis todavía no está listo cuando arranca el worker, reintenta la
    # conexión en vez de morir. En compose pasa constantemente.
    broker_connection_retry_on_startup=True,
)
