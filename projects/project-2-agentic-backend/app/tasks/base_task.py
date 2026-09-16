"""La clase base de las tareas: qué pasa cuando una muere del todo.

Celery expone hooks sobre `Task` que se disparan en momentos concretos:

    on_retry    → una vez POR CADA reintento
    on_failure  → UNA sola vez, cuando el fallo ya es definitivo
    on_success  → cuando terminó bien

La DLQ y el `failed` de la fila van en `on_failure` y no en `on_retry`: una tarea
que reintenta dos veces y se recupera no tiene que dejar rastro de fallo.
"""

import logging

from app.core.db import SessionFactory
from app.tasks import dead_letter
from app.tasks.celery_app import celery_app
from app.tasks.state import marcar_fallida

logger = logging.getLogger(__name__)


class AgentTask(celery_app.Task):
    """Base de las tareas del agente: cierra la fila y registra el fallo."""

    def on_failure(self, exc, task_id, args, kwargs, einfo) -> None:  # type: ignore[no-untyped-def]
        """Corre en el worker, en el mismo proceso que ejecutó la tarea.

        Ojo con los dos "task_id" que conviven acá y no son lo mismo:

            task_id   → el id del MENSAJE de Celery (un uuid)
            args[0]   → el id de TU fila en la tabla `tasks` (t_xxx)

        Confundirlos es buscar en la base un uuid que nunca estuvo ahí.
        """
        dominio_id = args[0] if args else kwargs.get("task_id")

        # Cerrar la fila. Si llegamos acá y la tarea sigue en `running`, es porque
        # se agotaron los reintentos: nadie más la va a mover.
        #
        # Sesión propia: la del cuerpo de la tarea ya se cerró cuando la excepción
        # salió del `with`.
        if dominio_id:
            try:
                with SessionFactory() as db:
                    marcar_fallida(db, dominio_id, f"{type(exc).__name__}: {exc}")
            except Exception:
                logger.exception("no se pudo marcar failed la tarea %s", dominio_id)

        # Este try/except no es defensivo por costumbre, es obligatorio: si
        # `on_failure` levanta, Celery se lo come en silencio. Un Redis caído acá
        # dejaría la DLQ vacía sin un solo aviso — y creerías que no falló nada.
        try:
            dead_letter.record_failure(
                celery_task_id=task_id,
                task_name=self.name,
                args=args,
                kwargs=kwargs,
                exception=exc,
                retries=self.request.retries,
            )
        except Exception:
            logger.exception("no se pudo registrar el fallo de %s en la DLQ", task_id)

        # El comportamiento original de Celery (el logging del fallo).
        # Sobreescribir un hook sin llamar a super() es perder cosas en silencio.
        super().on_failure(exc, task_id, args, kwargs, einfo)

    # El traceback NO va a la DLQ: son kilobytes por entrada por DEAD_LETTER_MAX,
    # y para eso están los logs del worker. En la DLQ va lo mínimo para triagear
    # y reprocesar; el detalle se busca en el log por id.
