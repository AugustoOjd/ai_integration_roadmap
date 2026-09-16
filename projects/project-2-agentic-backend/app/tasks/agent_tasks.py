"""La tarea de Celery que corre el agente.

Lo único que cruza a Redis es un `task_id`. Todo lo demás —quién es el dueño, qué
pidió, cuánto puede gastar— se **reconstruye** de la base del otro lado.

Eso es a propósito y por dos motivos. Uno es de seguridad: el mensaje viaja por
un broker que cualquiera con acceso puede leer y escribir, así que cuanto menos
lleve, mejor. El otro es que si el payload llevara el `user_id`, habría dos
lugares diciendo de quién es la corrida — el mensaje y la fila — y el día que
difieran no vas a saber cuál vale.

La consecuencia de que Redis sea escribible: alguien podría encolar un `task_id`
inventado. Por eso el worker no confía en lo que le llega y vuelve a leer todo.
"""

import logging

from app.agent.deps import AgentDeps
from app.agent.loop import ApprovalRequired, run_agent
from app.agent.repository import get_conversation
from app.core.db import SessionFactory
from app.core.models import Task
from app.tasks.base_task import AgentTask
from app.tasks.celery_app import celery_app
from app.tasks.retry_policy import MAX_REINTENTOS, REINTENTABLES, espera
from app.tasks.state import (
    marcar_corriendo,
    marcar_esperando_aprobacion,
    marcar_exitosa,
    marcar_fallida,
    registrar_reintento,
)

logger = logging.getLogger(__name__)


@celery_app.task(
    name="agent.execute",
    # `bind=True` hace que el primer parámetro sea la instancia de la tarea, que
    # es como se llega a `self.retry()` y a `self.request.retries`.
    bind=True,
    base=AgentTask,
    max_retries=MAX_REINTENTOS,
)
def execute_agent_task(self: Task, task_id: str) -> None:  # type: ignore[valid-type]
    """Corre el agente sobre una tarea ya creada.

    No devuelve nada, y es deliberado: el resultado va a la fila. Devolverlo
    además por el backend de Celery sería un segundo lugar donde vive la
    respuesta, con otro ciclo de vida y otra política de borrado.

    Y no re-lanza las excepciones. En el request había que dejarlas subir para
    que `errors.py` eligiera un código HTTP; acá no hay a quién contarle. Lo
    único que lograría propagar es marcar FAILURE en un backend que no es la
    fuente de verdad, mientras la fila —que sí lo es— ya quedó en `failed`.
    """
    # Su propia sesión de base. No hay request, así que no hay `get_db`: el `with`
    # es el que garantiza que la conexión vuelve al pool pase lo que pase.
    with SessionFactory() as db:
        tarea = db.get(Task, task_id)
        if tarea is None:
            # Un id que no existe. O alguien escribió en el broker, o la
            # conversación se borró entre el encolado y ahora. No es un error
            # que valga la pena reintentar: no hay nada que correr.
            logger.warning("tarea inexistente id=%s, se descarta", task_id)
            return

        conversacion = get_conversation(db, tarea.conversation_id)

        # El contexto autenticado, reconstruido. Acá se ve lo que el worker NO
        # tiene: no hay header, no hay token, no hay request. El dueño sale de la
        # conversación, que es la única fuente de verdad sobre de quién es esto.
        deps = AgentDeps(
            user_id=conversacion.user_id,
            conversation_id=conversacion.id,
            db=db,
        )

        # El prompt se lee ANTES de la transición: el CAS es un UPDATE que no
        # sincroniza la sesión, así que después el objeto queda desactualizado.
        prompt = tarea.prompt

        # El candado, y sólo en el PRIMER intento. Un reintento vuelve a entrar
        # acá con la fila ya en `running`: el CAS no prendería y la tarea se
        # descartaría sola, que es justo lo contrario de reintentar.
        #
        # `self.request.retries > 0` significa "esto es un reintento mío", que no
        # es lo mismo que "otro worker la tomó". La reentrega del broker —que sí
        # es otro— llega con retries en 0 y el candado la frena.
        if self.request.retries == 0 and not marcar_corriendo(db, task_id):
            logger.warning("tarea id=%s ya no está en pending, se descarta", task_id)
            return

        logger.info(
            "tomando tarea id=%s conversation=%s user=%s",
            task_id,
            conversacion.id,
            conversacion.user_id,
        )

        try:
            result = run_agent(db, conversacion.id, prompt, deps)

        except ApprovalRequired:
            # El loop se frenó esperando a un humano. Acá se ve el problema que
            # el request no tenía: no hay a quién devolverle un 202. La tarea
            # queda en `pending_approval` y enterarse es mirar la fila.
            logger.info("tarea id=%s esperando aprobación", task_id)
            if not marcar_esperando_aprobacion(db, task_id):
                logger.error("tarea id=%s: no se pudo pausar, ¿quién la movió?", task_id)
            return

        except REINTENTABLES as exc:
            # El mundo falló, no nuestro estado: se reintenta. La fila NO se marca
            # `failed` acá — sigue en `running`, porque esta ejecución no terminó.
            # Si se agotan los reintentos, `self.retry` re-lanza la excepción
            # original y el `on_failure` de AgentTask cierra la fila y escribe la
            # DLQ.
            db.rollback()
            intento = self.request.retries + 1
            demora = espera(exc, self.request.retries)
            registrar_reintento(db, task_id, intento)
            logger.warning(
                "tarea id=%s reintento %d/%d en %.1fs por %s",
                task_id,
                intento,
                MAX_REINTENTOS,
                demora,
                type(exc).__name__,
            )
            raise self.retry(exc=exc, countdown=demora)

        except Exception as exc:
            # Permanente: reintentar no lo arregla. Termina acá, con la razón en
            # la fila, y sin gastar tres veces lo mismo.
            #
            # El rollback va primero: run_agent pudo dejar la sesión con trabajo a
            # medias, y escribir el fallo encima de eso lo commitearía.
            db.rollback()
            logger.exception("tarea id=%s falló definitivamente", task_id)
            if not marcar_fallida(db, task_id, f"{type(exc).__name__}: {exc}"):
                logger.error("tarea id=%s: no se pudo marcar failed", task_id)
            return

        # Si esto no prende, alguien movió la fila mientras el agente corría. No
        # se pisa: el estado que ya está escrito gana, y queda el log para mirarlo.
        prendio = marcar_exitosa(
            db,
            task_id,
            {
                "answer": result.text,
                "iterations": result.iterations,
                "tools_used": result.tools_used,
                "usage": {
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                },
            },
        )
        if not prendio:
            logger.error(
                "tarea id=%s terminó bien pero ya no estaba en running: "
                "el resultado se descarta",
                task_id,
            )
            return

        logger.info(
            "tarea id=%s ok iterations=%d tools=%s",
            task_id,
            result.iterations,
            result.tools_used,
        )
