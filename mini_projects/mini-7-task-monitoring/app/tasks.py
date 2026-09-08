from app.base_task import DeadLetterTask
from app.celery_app import celery_app
from app.exceptions import TransientError
from app.services import external_api


# bind=True inyecta `self` (la Task): da acceso a self.request, donde vive el
# estado del mensaje que se está procesando (id, número de reintento, etc).
#
# name explícito: sin él el nombre se deriva del módulo ("app.tasks.flaky") y
# mover el archivo rompe los mensajes que ya están encolados apuntando al nombre
# viejo.
@celery_app.task(
    bind=True,
    name="tasks.flaky",
    # base= reemplaza la clase Task por defecto. `self` dentro de la tarea pasa
    # a ser una instancia de DeadLetterTask, y sus hooks son los que corren.
    base=DeadLetterTask,
    # ---------------------------------------------------- Política de retry
    # Qué excepciones disparan un reintento automático. Celery envuelve el
    # cuerpo de la tarea en un try/except de estos tipos y llama a self.retry()
    # por vos. Cualquier excepción que NO esté acá va directo a FAILURE.
    #
    # El match es por herencia: una subclase de TransientError también entra.
    autoretry_for=(TransientError,),
    # Backoff exponencial. El número es el FACTOR en segundos, y el delay del
    # reintento n es `factor * 2**n`: 2s, 4s, 8s.
    #
    # `retry_backoff=True` equivale a factor 1 (1s, 2s, 4s). Uso 2 acá solo para
    # que los saltos se vean cómodos en el log.
    #
    # CUIDADO: si ponés `autoretry_for` y te olvidás de `retry_backoff`, Celery
    # usa `default_retry_delay` = 180 segundos. Vas a jurar que no reintenta
    # cuando en realidad está esperando 3 minutos.
    retry_backoff=2,
    # Techo del delay. Sin esto, el reintento 10 esperaría 2048 segundos: el
    # exponencial crece más rápido de lo que uno intuye.
    retry_backoff_max=60,
    # Aleatoriza el delay dentro del intervalo (full jitter: un valor al azar
    # entre 0 y el backoff calculado, no "el backoff ± un poco").
    #
    # Por qué importa: si 500 tareas fallan en el mismo segundo porque se cayó
    # un servicio, sin jitter las 500 reintentan EXACTAMENTE al segundo 2, y de
    # nuevo al 4, y al 8. Convertiste un pico en varios picos sincronizados
    # golpeando a un servicio que trata de levantarse. Eso es el thundering herd.
    # El jitter desparrama esos reintentos en el tiempo.
    retry_jitter=True,
    # 3 REINTENTOS = 4 ejecuciones en total, contando la primera.
    max_retries=3,
)
def flaky(self, fail_times: int) -> dict:
    """Falla las primeras `fail_times` veces y después funciona.

    Simula un servicio externo intermitente, que es el caso canónico de
    reintento. Con `fail_times` mayor que max_retries la tarea agota los
    reintentos y termina en FAILURE: sirve para ver los dos desenlaces.
    """
    # self.request.retries arranca en 0 y Celery lo incrementa en cada reintento.
    # Es lo que hace este ejemplo determinista, sin random.
    intento = self.request.retries + 1

    if self.request.retries < fail_times:
        # Fijate en la diferencia con el mini 6: acá NO se llama a self.retry().
        # Solo se levanta la excepción y `autoretry_for` hace el resto —calcula
        # el backoff, aplica el jitter, cuenta los reintentos y reencola—.
        # La tarea describe QUÉ salió mal; la política de CÓMO responder vive en
        # el decorador.
        raise TransientError(f"Fallo simulado en el intento {intento}")

    # El return se serializa a JSON y se guarda en el backend bajo el task_id.
    # Devolvemos un dict y no un valor suelto para que la respuesta tenga forma
    # estable si mañana agregamos campos.
    return {
        "task_id": self.request.id,
        "intentos": intento,
        "status": "recuperado",
    }


@celery_app.task(
    bind=True,
    name="tasks.fetch_resource",
    base=DeadLetterTask,
    # Misma política de backoff que `flaky`, pero acá la tupla dice algo más
    # fuerte: SOLO TransientError entra al ciclo de reintentos.
    #
    # PermanentError hereda de TaskError, no de TransientError, así que no
    # matchea y no se reintenta. Un bug (TypeError, KeyError) tampoco: va
    # directo a FAILURE en el primer intento, que es lo que querés para un bug.
    autoretry_for=(TransientError,),
    retry_backoff=2,
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=3,
)
def fetch_resource(self, resource_id: str, simulated_status: int = 200) -> dict:
    """Trae un recurso de un servicio externo, reintentando solo lo que vale.

    La tarea es deliberadamente delgada: toda la decisión de qué error es cuál
    vive en `services/external_api.py`, que no sabe nada de Celery. Acá solo
    queda la orquestación.
    """
    # Sin try/except. Si `fetch` levanta TransientError, Celery lo atrapa por
    # el `autoretry_for` y reencola; si levanta PermanentError, lo deja pasar y
    # la tarea muere. No hay nada que decidir en este nivel.
    recurso = external_api.fetch(resource_id, simulated_status)

    return {
        "task_id": self.request.id,
        "intentos": self.request.retries + 1,
        **recurso,
    }
