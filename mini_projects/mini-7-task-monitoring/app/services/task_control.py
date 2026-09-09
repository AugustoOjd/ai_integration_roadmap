"""Control del cluster: operaciones que CAMBIAN algo.

`monitoring.py` pregunta (inspect); esto ordena (control). La distinción no es
cosmética: las lecturas se pueden repetir sin consecuencias y las órdenes no.

Ambas viajan por el mismo canal de broadcast del broker, pero con una diferencia
crucial: `inspect()` ESPERA respuesta, `revoke()` no. Es fire-and-forget.
"""

from celery.result import AsyncResult

from app.celery_app import celery_app


def revoke(task_id: str, *, terminate: bool = False) -> None:
    """Cancela una tarea. Devuelve None SIEMPRE, incluso si el id no existe.

    Dos escenarios muy distintos según dónde esté la tarea:

    - TODAVÍA EN LA COLA: los workers anotan el id en un set de revocados que
      tienen en memoria. Cuando a ese mensaje le toque, lo descartan sin
      ejecutarlo. Barato y seguro.

    - YA EJECUTÁNDOSE: sin `terminate` no pasa nada — el mensaje ya salió de la
      cola y la tarea sigue hasta terminar. Hace falta `terminate=True`, que
      MATA con una señal al proceso hijo que la está corriendo.

    Sobre terminate=True, que por algo no es el default:

      * La tarea muere en el medio. No corren los `finally`, no se cierran
        conexiones, no hay cleanup. Si estaba a mitad de una escritura, quedó a
        mitad. Solo es seguro si la tarea es idempotente o no tiene efectos.
      * La señal va al PROCESO HIJO. Con el pool prefork, matarlo hace que el
        worker levante otro: es una operación cara.
      * El set de revocados vive en MEMORIA del worker. Si el worker reinicia,
        se olvida — y un mensaje revocado que siguiera en la cola se ejecutaría
        igual. Para que sobreviva hay que arrancar el worker con `--statedb`.

    No devolvemos nada porque Celery no nos da nada: la orden se publica en el
    broker y la función retorna. No sabemos si había workers escuchando, ni si
    el id existía, ni si alguno la aplicó. La única confirmación posible es
    consultar después el estado de la tarea y ver si dice REVOKED.
    """
    celery_app.control.revoke(task_id, terminate=terminate)


def state_of(task_id: str) -> str:
    """Estado actual de una tarea, para verificar el efecto de un revoke.

    Con REVOKED aparece la misma ambigüedad de siempre: si sigue en PENDING
    puede ser que la revocación no llegó todavía, o que ese id nunca existió.
    """
    return AsyncResult(task_id, app=celery_app).state
