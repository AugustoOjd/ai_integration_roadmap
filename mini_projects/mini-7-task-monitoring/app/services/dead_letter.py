"""Dead letter queue: dónde termina lo que no se pudo procesar.

Una tarea que agota sus reintentos queda en FAILURE en el backend de resultados
y desaparece cuando expira `result_expires` (1 hora acá). Después de eso el
fallo no existió: nadie puede auditarlo, alertarlo ni reprocesarlo.

RabbitMQ tiene dead lettering nativo (`x-dead-letter-exchange`). Con Redis como
broker no existe: hay que construirlo, y esto es exactamente eso.

Implementación: una lista de Redis usada como stack (LPUSH al frente), acotada
con LTRIM. Lo más nuevo queda arriba, que es lo que uno quiere leer primero
cuando algo se está rompiendo ahora mismo.
"""

import json
from datetime import UTC, datetime
from typing import Any

import redis

from app.config import settings

# Un cliente a nivel de módulo, no uno por llamada. `from_url` construye un
# CONNECTION POOL por detrás: las conexiones se reutilizan entre llamadas y
# entre threads (el cliente es thread-safe). Crear un cliente por invocación
# abriría un socket TCP nuevo cada vez.
#
# decode_responses=True: Redis habla en bytes. Sin esto, cada lectura devuelve
# b'{"task_id": ...}' y habría que llamar .decode() en todos lados.
_client = redis.Redis.from_url(settings.DEAD_LETTER_URL, decode_responses=True)


def record_failure(
    *,
    task_id: str,
    task_name: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    exception: BaseException,
    retries: int,
) -> None:
    """Guarda un fallo definitivo en la DLQ.

    Se llama UNA vez por tarea muerta, no una por reintento.

    Guardamos los `args` y `kwargs` originales a propósito: sin ellos la entrada
    dice "algo falló" y no se puede reprocesar. Con ellos, reencolar es
    `celery_app.send_task(task_name, args, kwargs)`.
    """
    entry = {
        "task_id": task_id,
        "task_name": task_name,
        "args": list(args),
        "kwargs": kwargs,
        # El TIPO de la excepción, no solo el mensaje: es lo que permite después
        # agrupar por causa ("42 PermanentError, 3 TransientError") en vez de
        # comparar strings.
        "exc_type": type(exception).__name__,
        "exc_message": str(exception),
        # Cuántos reintentos se consumieron antes de rendirse. Un fallo con 0
        # reintentos fue permanente; con 3, se agotó el presupuesto.
        "retries": retries,
        # Timestamp del worker, en UTC y en ISO 8601. UTC porque los workers
        # pueden estar en zonas distintas y las horas locales no se comparan.
        "failed_at": datetime.now(UTC).isoformat(),
    }

    # default=str: red de seguridad. Si un arg no es serializable a JSON (no
    # debería pasar, viajó como JSON hasta acá), preferimos guardar su repr
    # antes que romper el registro del fallo.
    payload = json.dumps(entry, default=str)

    # LPUSH + LTRIM en un pipeline: los dos comandos viajan en un solo round
    # trip y Redis los ejecuta seguidos. Sin el LTRIM, una tarea que falla en
    # bucle llena la memoria de Redis — una DLQ sin techo es una fuga lenta.
    #
    # LTRIM 0..MAX-1 conserva los MAX más NUEVOS y descarta los viejos: cuando
    # algo se rompe, lo que importa es lo que está pasando ahora.
    pipe = _client.pipeline()
    pipe.lpush(settings.DEAD_LETTER_KEY, payload)
    pipe.ltrim(settings.DEAD_LETTER_KEY, 0, settings.DEAD_LETTER_MAX - 1)
    pipe.execute()


def list_failures(limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    """Devuelve los fallos más recientes primero.

    LRANGE usa índices inclusivos en AMBOS extremos: para `limit` elementos
    desde `offset`, el final es offset + limit - 1. Es el off-by-one clásico
    de Redis.
    """
    raw = _client.lrange(settings.DEAD_LETTER_KEY, offset, offset + limit - 1)
    return [json.loads(item) for item in raw]


def replay(limit: int = 50) -> int:
    """Reencola los fallos más recientes y los saca de la DLQ.

    Esta es la única función del módulo que habla con Celery, y es la razón de
    ser de toda la fase: sin `task_name` + `args` + `kwargs` guardados, esto no
    se puede escribir.

    Vive acá y no en la ruta porque necesita el string CRUDO de cada entrada:
    LREM borra por valor exacto, así que hay que conservar el JSON tal como se
    guardó para poder eliminar exactamente la entrada que se reenvió.
    """
    # Import local, no arriba: `app.base_task` importa este módulo, y ese
    # importa `app.celery_app`. A nivel de módulo esto sería un ciclo.
    from app.celery_app import celery_app

    raw_entries = _client.lrange(settings.DEAD_LETTER_KEY, 0, limit - 1)
    reenviadas = 0

    for raw in raw_entries:
        entry = json.loads(raw)

        # send_task encola POR NOMBRE, sin importar la función. La API no
        # necesita tener importada la tarea —ni siquiera saber que existe— para
        # reencolarla. Es el mismo mecanismo por el que un worker resuelve un
        # mensaje: el nombre es el contrato.
        celery_app.send_task(
            entry["task_name"],
            args=entry["args"],
            kwargs=entry["kwargs"],
        )

        # Primero encolar, después borrar. Si el proceso muere entre las dos
        # operaciones, la entrada se reenvía dos veces; al revés, se perdería
        # para siempre. Entre duplicar y perder, se duplica — y por eso las
        # tareas tienen que ser idempotentes (lo mismo que ya exige
        # `task_acks_late`).
        #
        # LREM con count=1 borra la primera coincidencia desde el frente.
        _client.lrem(settings.DEAD_LETTER_KEY, 1, raw)
        reenviadas += 1

    return reenviadas


def count() -> int:
    """Cuántos fallos hay guardados. LLEN sobre una key inexistente es 0."""
    return _client.llen(settings.DEAD_LETTER_KEY)


def clear() -> int:
    """Vacía la DLQ y devuelve cuántas entradas se borraron.

    Contamos antes de borrar porque DEL devuelve la cantidad de KEYS eliminadas
    (0 o 1), no la de elementos de la lista.
    """
    total = count()
    _client.delete(settings.DEAD_LETTER_KEY)
    return total
