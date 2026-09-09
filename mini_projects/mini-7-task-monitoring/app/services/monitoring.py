"""Introspección del cluster de workers.

Hasta acá todo fue sobre UNA tarea: encolarla, reintentarla, ver su progreso.
Esto es sobre la FLOTA: quién está vivo, qué está corriendo, cuánto procesó cada
worker.

EL DETALLE QUE CAMBIA TODO
--------------------------
`celery_app.control.inspect()` NO lee una base de datos. Publica un mensaje de
broadcast en el broker, cada worker lo recibe, responde por su cuenta, y el
cliente junta las respuestas que llegaron ANTES DEL TIMEOUT.

Es una llamada de red con espera, y de ahí salen las tres consecuencias que
gobiernan el diseño de este módulo:

1. Si no contesta nadie, devuelve `None` — no un dict vacío. `for w in
   inspect.active()` explota con TypeError justo cuando el cluster se cayó, o
   sea en el peor momento posible.
2. Cada llamada cuesta su timeout. Cuatro métodos en un dashboard son cuatro
   esperas, no una.
3. Lo que devuelve es un SNAPSHOT del instante, no una serie temporal. Sirve
   para "¿qué está pasando ahora?", no para "¿cuánto falló ayer?".
"""

from typing import Any

from app.celery_app import celery_app
from app.config import settings

# Un dict indexado por nombre de worker: {"worker1@abc123": [...], ...}. Es la
# forma que devuelve todo `inspect`, y por eso pusimos --hostname fijo en el
# compose: si el nombre cambia en cada arranque, esta clave es inútil.
PorWorker = dict[str, Any]


def _inspect():
    """Cliente de inspección con timeout explícito.

    El default de Celery es 1 segundo, igual que el nuestro, pero dejarlo
    implícito significa que el presupuesto de latencia de tu API depende de un
    default de una librería. Explícito y configurable.
    """
    return celery_app.control.inspect(timeout=settings.INSPECT_TIMEOUT)


def _normalizar(respuesta: PorWorker | None) -> PorWorker:
    """Convierte el `None` de "no contestó nadie" en un dict vacío.

    Se llama en TODAS las funciones de abajo. Es la única defensa contra el
    TypeError, y sin ella cada consumidor tendría que acordarse del caso None.

    Ojo: acá se pierde información a propósito. Después de esto, "no hay
    workers" y "hay workers sin nada que hacer" se ven igual. Por eso existe
    `workers_online()`: esa pregunta se responde con ping(), no mirando si un
    dict de tareas está vacío.
    """
    return respuesta or {}


def workers_online() -> list[str]:
    """Nombres de los workers vivos. La consulta más barata del módulo.

    ping() solo pide un "pong": no serializa listas de tareas ni estadísticas.
    Es la primera pregunta que hay que hacer, porque si devuelve [] ya sabés que
    todo lo demás va a venir vacío y podés ahorrarte los otros broadcasts.
    """
    return sorted(_normalizar(_inspect().ping()))


def active_tasks() -> PorWorker:
    """Tareas EJECUTÁNDOSE en este instante, por worker.

    Cada entrada trae id, name, args, kwargs y time_start. Es lo que responde
    "¿qué está haciendo el sistema ahora mismo?".
    """
    return _normalizar(_inspect().active())


def reserved_tasks() -> PorWorker:
    """Tareas que el worker ya sacó de la cola pero todavía no empezó.

    Es el prefetch: mensajes reservados para este worker, invisibles para los
    demás. Con `worker_prefetch_multiplier=1` (Fase 0) esta lista es corta y se
    puede leer; con el default de 4 por proceso, un worker acapara decenas de
    mensajes y esta vista deja de decir algo útil.
    """
    return _normalizar(_inspect().reserved())


def scheduled_tasks() -> PorWorker:
    """Tareas con ETA o countdown esperando su hora.

    ACÁ VIVEN LOS REINTENTOS PENDIENTES. Cuando una tarea de la Fase 1 falla y
    Celery la reencola con countdown, queda en esta lista hasta que le toca. Si
    querés ver el backoff con tus propios ojos, es el método que hay que mirar:
    cada entrada trae el `eta`, o sea el momento exacto del próximo intento.
    """
    return _normalizar(_inspect().scheduled())


def worker_stats() -> PorWorker:
    """Estadísticas por worker: pool, concurrencia, totales por tarea, uptime.

    `total` es acumulado DESDE QUE ARRANCÓ EL PROCESO. Reiniciás el worker y
    vuelve a cero: sirve para mirar en el momento, no como métrica histórica.
    Para eso hacen falta Prometheus y compañía.
    """
    return _normalizar(_inspect().stats())


def cluster_snapshot() -> dict[str, Any]:
    """Una foto completa del cluster, en UNA sola pasada.

    Cuidado con el costo: son cuatro broadcasts, cada uno con su timeout. Con
    INSPECT_TIMEOUT=1.0 y el cluster caído, esta función tarda ~4 segundos.

    Por eso el cortocircuito: si no hay un solo worker vivo, las otras tres
    consultas van a devolver None igual, así que ni las hacemos. Un cluster
    muerto se reporta en ~1 segundo en vez de en 4 — y es justo el caso en el
    que alguien está mirando con urgencia.
    """
    online = workers_online()

    if not online:
        return {
            "healthy": False,
            "workers": [],
            "active": {},
            "reserved": {},
            "scheduled": {},
            "stats": {},
        }

    return {
        "healthy": True,
        "workers": online,
        "active": active_tasks(),
        "reserved": reserved_tasks(),
        "scheduled": scheduled_tasks(),
        "stats": worker_stats(),
    }
