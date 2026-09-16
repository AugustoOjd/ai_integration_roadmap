"""Dónde termina lo que no se pudo procesar.

Una tarea que agota sus reintentos queda en FAILURE en el backend de Celery y
desaparece cuando vence `result_expires`. Después de eso el fallo no existió:
nadie puede auditarlo, alertarlo ni reprocesarlo.

RabbitMQ tiene dead lettering nativo; con Redis como broker no existe y hay que
construirlo. Esto es exactamente eso: una lista usada como stack (LPUSH al
frente) y acotada con LTRIM, así lo más nuevo queda arriba — que es lo que querés
leer primero cuando algo se está rompiendo ahora mismo.

La fila `tasks` ya dice que algo falló y por qué. Esto agrega lo que la fila no
tiene: los argumentos originales, que es lo único que hace **reprocesable** un
fallo.
"""

import json
from datetime import UTC, datetime
from typing import Any

import redis

from app.core.config import settings

# Un cliente de módulo, no uno por llamada: `from_url` arma un connection pool
# por detrás y el cliente es thread-safe.
# decode_responses=True porque si no cada lectura vuelve como bytes.
_client = redis.Redis.from_url(str(settings.DEAD_LETTER_URL), decode_responses=True)


def record_failure(
    *,
    celery_task_id: str,
    task_name: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    exception: BaseException,
    retries: int,
) -> None:
    """Guarda un fallo definitivo. Se llama una vez por tarea muerta, no por reintento."""
    entrada = {
        "celery_task_id": celery_task_id,
        "task_name": task_name,
        # Sin los args originales la entrada dice "algo falló" y no se puede
        # reprocesar. Con ellos, reencolar es una línea.
        "args": list(args),
        "kwargs": kwargs,
        # El TIPO además del mensaje: es lo que permite agrupar por causa
        # ("42 RateLimitError, 3 BudgetExceededError") sin comparar strings.
        "exc_type": type(exception).__name__,
        "exc_message": str(exception),
        # 0 reintentos = el fallo fue permanente. 3 = era transitorio y duró
        # demasiado. Son dos problemas distintos y este número los separa.
        "retries": retries,
        "failed_at": datetime.now(UTC).isoformat(),
    }

    # default=str es red de seguridad: si algo no serializa, preferimos guardar su
    # repr antes que romper el registro del fallo.
    payload = json.dumps(entrada, default=str)

    # Los dos comandos en un pipeline: un solo round trip y Redis los ejecuta
    # seguidos. LTRIM conserva los MAX más nuevos.
    pipe = _client.pipeline()
    pipe.lpush(settings.DEAD_LETTER_KEY, payload)
    pipe.ltrim(settings.DEAD_LETTER_KEY, 0, settings.DEAD_LETTER_MAX - 1)
    pipe.execute()


def list_failures(limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    """Los fallos más recientes primero.

    LRANGE usa índices inclusivos en los dos extremos: para `limit` elementos
    desde `offset`, el final es `offset + limit - 1`. Es el off-by-one clásico.
    """
    crudos = _client.lrange(settings.DEAD_LETTER_KEY, offset, offset + limit - 1)
    return [json.loads(item) for item in crudos]


def count() -> int:
    """LLEN sobre una key que no existe devuelve 0."""
    return _client.llen(settings.DEAD_LETTER_KEY)


def clear() -> int:
    """Vacía la DLQ y devuelve cuántas entradas había.

    Se cuenta antes de borrar porque DEL devuelve cuántas KEYS eliminó (0 o 1),
    no cuántos elementos tenía la lista.
    """
    total = count()
    _client.delete(settings.DEAD_LETTER_KEY)
    return total


def replay(limit: int = 50) -> int:
    """Reencola los fallos más recientes y los saca de la DLQ.

    Es la razón de ser del formato de la entrada: sin `task_name` + `args`
    guardados, esto no se puede escribir.
    """
    # Import local: este módulo lo importa `base_task`, que importa `celery_app`.
    # Arriba sería un ciclo.
    from app.tasks.celery_app import celery_app

    crudos = _client.lrange(settings.DEAD_LETTER_KEY, 0, limit - 1)
    reenviadas = 0

    for crudo in crudos:
        entrada = json.loads(crudo)

        # `send_task` encola POR NOMBRE, sin importar la función: quien reencola
        # no necesita tener importada la tarea. El nombre es el contrato, igual
        # que del lado del worker.
        celery_app.send_task(
            entrada["task_name"], args=entrada["args"], kwargs=entrada["kwargs"]
        )

        # Primero encolar, después borrar. Si el proceso muere entre las dos, la
        # entrada se reenvía dos veces; al revés se perdería para siempre. Entre
        # duplicar y perder se duplica — y por eso las tareas tienen que ser
        # idempotentes.
        _client.lrem(settings.DEAD_LETTER_KEY, 1, crudo)
        reenviadas += 1

    return reenviadas
