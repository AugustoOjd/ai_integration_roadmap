"""La instancia de Celery y la configuración del worker.

    uv run celery -A app.tasks.celery_app worker --loglevel=info
"""

import logging

from celery import Celery
from celery.signals import worker_process_init

from app.core.config import settings
from app.core.db import engine

logger = logging.getLogger(__name__)

celery_app = Celery(
    "agentic",
    broker=str(settings.CELERY_BROKER_URL),
    backend=str(settings.CELERY_RESULT_BACKEND),
    # Los módulos con tareas se importan explícitamente. Un `@celery_app.task` en
    # un módulo que el worker nunca importa no existe para el worker, y el
    # síntoma es un `Received unregistered task` que no dice dónde buscar.
    include=["app.tasks.agent_tasks", "app.tasks.reaper"],
)

celery_app.conf.update(
    # JSON y no pickle, y esto no es una preferencia de formato.
    #
    # Deserializar un pickle ejecuta código: cualquiera que pueda escribir en el
    # broker puede ejecutar lo que quiera en tus workers. Y el broker es un Redis
    # al que, en cuanto salgas de localhost, le puede llegar tráfico que no es
    # tuyo. `accept_content` es la mitad que importa: es lo que hace que un
    # payload pickle llegue y sea rechazado.
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # Todo en UTC. Los workers pueden correr en máquinas con zonas distintas, y
    # un ETA interpretado en dos husos es una tarea que corre a destiempo.
    timezone="UTC",
    enable_utc=True,
    # El worker publica STARTED además de PENDING/SUCCESS/FAILURE.
    task_track_started=True,
    # ---- La entrega al menos una vez -------------------------------------
    #
    # Por default Celery confirma el mensaje ANTES de ejecutarlo: si el worker se
    # muere a mitad, la tarea se perdió y nadie se entera. Con `acks_late` la
    # confirmación va DESPUÉS, así que un worker que muere deja el mensaje sin
    # confirmar y el broker se lo da a otro.
    #
    # El precio es exactamente el problema de esta fase: un worker que muere
    # después de ejecutar pero antes de confirmar hace que la tarea corra DOS
    # VECES. No es un riesgo, es el diseño — "exactly once" no existe, y lo que
    # se elige es entre perder y duplicar.
    #
    # Elegimos duplicar, y la defensa es el candado del `status` de la fila más
    # el registro de `tool_executions`.
    task_acks_late=True,
    # Cuando el worker muere de verdad (SIGKILL, OOM), el mensaje se re-encola en
    # vez de descartarse. Sin esto, `acks_late` no protege del caso que más
    # importa. La contracara: una tarea que mata al worker se re-entrega para
    # siempre, y lo que la frena es el CAS de `marcar_corriendo`.
    task_reject_on_worker_lost=True,
    # Los resultados se vencen solos. Sin esto Redis acumula una clave por tarea
    # para siempre, y como nadie las lee, es memoria que sólo crece.
    result_expires=3600,
    # ---- El reloj ---------------------------------------------------------
    #
    # Lo dispara `celery beat`, que es un proceso APARTE del worker: beat sólo
    # encola, el worker ejecuta. Si beat no corre, el reaper no existe y las
    # tareas huérfanas se acumulan en silencio — que es el modo de falla más
    # fácil de no notar de todo el proyecto.
    #
    # Y beat tiene que correr UNA sola vez en el cluster: dos instancias encolan
    # el reaper dos veces. Acá no importa (el reaper es idempotente por el CAS),
    # pero con una tarea que mande mails sí.
    beat_schedule={
        "reap-stale-tasks": {
            "task": "agent.reap_stale",
            "schedule": float(settings.REAPER_INTERVALO_S),
        },
        "expire-approvals": {
            "task": "agent.expire_approvals",
            "schedule": float(settings.REAPER_INTERVALO_S),
        },
        "sweep-reservations": {
            "task": "agent.sweep_reservations",
            "schedule": float(settings.REAPER_INTERVALO_S),
        },
    },
)

# ---------------------------------------------------------------------------
# El backend de Celery NO es la fuente de verdad
# ---------------------------------------------------------------------------
#
# Está configurado para poder mirar el transporte con Flower, y para nada más.
# El estado del negocio sale de la tabla `tasks`, y ningún endpoint de esta app
# construye un `AsyncResult`. Tres motivos concretos:
#
#   1. No sabe de tu dominio. `pending_approval` no existe en su vocabulario.
#   2. No sobrevive a un FLUSHDB, y vas a hacer uno para destrabar la cola.
#   3. Su PENDING significa "no sé nada de esta tarea", que es INDISTINGUIBLE de
#      un id inventado: `AsyncResult("cualquier-cosa").status` devuelve PENDING
#      en vez de un error. Un GET construido sobre eso le contesta "en cola" a
#      algo que no existió nunca.
#
# Si algún día aparece un `AsyncResult` en `app/api/`, es un bug.


@worker_process_init.connect
def _resetear_pool(**kwargs: object) -> None:
    """Cada hijo del worker abre conexiones propias a Postgres.

    El pool prefork de Celery forkea procesos hijos DESPUÉS de importar los
    módulos, así que el engine —que se crea al importar `app.core.db`— ya tiene
    conexiones abiertas cuando eso pasa. Los hijos heredan esos descriptores y
    terminan dos procesos escribiendo en el mismo socket: errores de protocolo,
    resultados de la query de otro, cuelgues intermitentes.

    `close=False` suelta el pool sin cerrar los sockets heredados. Cerrarlos
    mataría las conexiones que el proceso padre todavía usa.
    """
    engine.dispose(close=False)
    logger.info("pool de conexiones reseteado para este worker")
