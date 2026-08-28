import time

from app.celery_app import celery_app


# bind=True inyecta `self` (la Task): da acceso a self.request.id y a self.retry.
# name explícito: sin él, el nombre se deriva del módulo ("app.tasks.slow_double")
# y mover el archivo rompe los mensajes ya encolados.
@celery_app.task(bind=True, name="tasks.slow_double")
def slow_double(self, value: int) -> dict:
    """Duplica un número, lento a propósito para poder observar STARTED."""
    # self.request son los metadatos del mensaje que el worker está procesando.
    task_id = self.request.id

    # El sleep hace de "trabajo caro". El worker es un proceso normal y
    # síncrono: bloquear aquí es correcto, no congela nada más.
    time.sleep(5)

    result = value * 2

    # El return se serializa a JSON y se guarda en el backend bajo el task_id.
    # Devolvemos un dict y no un string suelto para que /result tenga forma
    # estable si mañana agregamos campos.
    return {"task_id": task_id, "input": value, "result": result}


# max_retries=3 son 3 REINTENTOS (4 ejecuciones en total, contando la primera).
@celery_app.task(bind=True, name="tasks.flaky", max_retries=3)
def flaky(self, fail_times: int) -> dict:
    """Falla las primeras `fail_times` veces y luego funciona.

    Simula un servicio externo intermitente: el caso típico de reintento.
    """
    # self.request.retries arranca en 0 y lo incrementa Celery en cada reintento.
    # Es lo que hace determinista este ejemplo, sin random.
    intento = self.request.retries + 1

    if self.request.retries < fail_times:
        # Backoff exponencial: 1s, 2s, 4s. Reintentar de inmediato contra un
        # servicio caído solo lo martilla; hay que darle tiempo a recuperarse.
        countdown = 2**self.request.retries

        # self.retry() reencola ESTE mismo mensaje (mismo task_id) y levanta
        # una excepción Retry para cortar acá. El `raise` es por legibilidad:
        # deja claro que la función no sigue.
        raise self.retry(
            exc=RuntimeError(f"Fallo simulado en el intento {intento}"),
            countdown=countdown,
        )

    return {"task_id": self.request.id, "intentos": intento, "status": "recuperado"}
