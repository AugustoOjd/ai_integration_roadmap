"""Clase base de las tareas: el enganche entre Celery y la dead letter queue.

Celery expone hooks en la clase `Task` que se disparan en momentos concretos del
ciclo de vida. Sobreescribir uno acá y usar esta clase como `base=` evita repetir
el mismo try/except en cada tarea.
"""

import logging

from app.celery_app import celery_app
from app.services import dead_letter

logger = logging.getLogger(__name__)


class DeadLetterTask(celery_app.Task):
    """Registra en la DLQ toda tarea que muere de forma definitiva.

    Los hooks relevantes y CUÁNDO se llaman:

        on_retry    → una vez por cada reintento. Con max_retries=3 corre 3 veces.
        on_failure  → UNA sola vez, cuando el fallo ya es definitivo: o se
                      agotaron los reintentos, o la excepción no era reintentable.
        on_success  → cuando la tarea termina bien.

    Por eso la DLQ va en `on_failure` y no en `on_retry`: una tarea que reintenta
    dos veces y se recupera no debe dejar rastro acá. Solo lo que se perdió.
    """

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Corre en el WORKER, en el mismo proceso que ejecutó la tarea.

        Args:
            exc: la excepción que mató a la tarea (el objeto, no el texto).
            task_id: el id del mensaje.
            args, kwargs: los argumentos ORIGINALES con los que se encoló. Son
                lo que hace reprocesable a la entrada.
            einfo: ExceptionInfo, con el traceback completo en `einfo.traceback`.
        """
        # Este try/except NO es defensivo por costumbre, es obligatorio.
        #
        # Si on_failure levanta una excepción, Celery se la come en silencio: no
        # aparece como fallo de la tarea (que ya falló) ni la ves por ningún
        # lado. Un Redis caído acá te dejaría una DLQ vacía sin un solo aviso,
        # que es peor que no tener DLQ: creerías que no falló nada.
        try:
            dead_letter.record_failure(
                task_id=task_id,
                task_name=self.name,
                args=args,
                kwargs=kwargs,
                exception=exc,
                # self.request.retries: cuántos reintentos se consumieron.
                # 0 = murió en el primer intento (fue permanente).
                # 3 = agotó el presupuesto (fue transitorio y duró demasiado).
                retries=self.request.retries,
            )
        except Exception:
            # .exception() incluye el traceback. Si la DLQ falla, al menos que
            # quede en el log del worker: es la última red que nos queda.
            logger.exception("No se pudo registrar el fallo de %s en la DLQ", task_id)

        # El comportamiento original de Celery (logging del fallo). Sobreescribir
        # un hook sin llamar a super() es una forma silenciosa de perder cosas.
        super().on_failure(exc, task_id, args, kwargs, einfo)

    # Nota sobre el traceback: NO lo guardamos en la DLQ. Ocupa kilobytes por
    # entrada, multiplicado por DEAD_LETTER_MAX es memoria de Redis, y para eso
    # están los logs del worker. En la DLQ va lo mínimo para triagear y
    # reprocesar; el detalle se busca en el log por task_id.
