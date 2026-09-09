"""Endpoints de monitoreo.

Regla que gobierna todo este archivo: **un endpoint de monitoreo nunca debe
caerse cuando el sistema está caído**. Es justo cuando alguien lo está mirando.

Por eso ninguna ruta devuelve 500 ni 503 si no hay workers: responden 200 con
`healthy: false` y listas vacías. El 200 dice "la pregunta se pudo responder";
el `healthy` dice cuál es la respuesta. Mezclar las dos cosas hace que el
cliente no pueda distinguir "el cluster está caído" de "el endpoint está roto".
"""

from typing import Any

from fastapi import APIRouter

from app.schemas import (
    ActiveTask,
    ActiveTasksResponse,
    DashboardResponse,
    ScheduledTask,
    ScheduledTasksResponse,
    WorkersResponse,
    WorkerSummary,
)
from app.services import dead_letter, monitoring

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


# ---------------------------------------------------------------- traductores
# Celery devuelve estructuras anidadas por worker y con nombres propios. Estas
# funciones las aplanan a nuestros schemas. Todo con .get(): una clave que
# cambie de nombre en una versión nueva debe degradar el campo, no tumbar el
# endpoint de monitoreo.


def _aplanar_activas(por_worker: dict[str, Any]) -> list[ActiveTask]:
    return [
        ActiveTask(
            worker=worker,
            task_id=tarea.get("id", ""),
            name=tarea.get("name", ""),
            args=tarea.get("args"),
            kwargs=tarea.get("kwargs"),
            started_at=tarea.get("time_start"),
        )
        for worker, tareas in por_worker.items()
        for tarea in tareas
    ]


def _aplanar_agendadas(por_worker: dict[str, Any]) -> list[ScheduledTask]:
    # Ojo con la forma: en `scheduled()` los datos de la tarea NO están en el
    # primer nivel como en `active()`, sino anidados en "request". El nivel de
    # arriba describe la PROGRAMACIÓN (eta, priority) y el de adentro, la tarea.
    return [
        ScheduledTask(
            worker=worker,
            task_id=entrada.get("request", {}).get("id", ""),
            name=entrada.get("request", {}).get("name", ""),
            eta=entrada.get("eta"),
        )
        for worker, entradas in por_worker.items()
        for entrada in entradas
    ]


def _resumir_workers(stats: dict[str, Any]) -> list[WorkerSummary]:
    return [
        WorkerSummary(
            name=nombre,
            concurrency=datos.get("pool", {}).get("max-concurrency"),
            pool=datos.get("pool", {}).get("implementation"),
            uptime=datos.get("uptime"),
            total=datos.get("total", {}),
        )
        for nombre, datos in stats.items()
    ]


# -------------------------------------------------------------------- rutas


@router.get("/workers", response_model=WorkersResponse)
def get_workers() -> WorkersResponse:
    """Qué workers están vivos y cómo están configurados.

    Es la respuesta a "¿hay quién ejecute mis tareas?", que es una pregunta
    distinta a la de /health. /health dice si ESTA API responde; una API sana
    con cero workers acepta tareas que nadie va a ejecutar nunca.
    """
    stats = monitoring.worker_stats()
    return WorkersResponse(healthy=bool(stats), workers=_resumir_workers(stats))


@router.get("/active", response_model=ActiveTasksResponse)
def get_active() -> ActiveTasksResponse:
    """Qué se está ejecutando en este instante.

    Snapshot, no serie temporal: dos llamadas seguidas devuelven cosas
    distintas y ninguna es "la verdad" — son dos momentos.
    """
    # Se pregunta primero por los workers para poder distinguir dos situaciones
    # que, mirando solo las tareas, se ven idénticas: "no hay nadie" y "hay
    # workers ociosos". En las dos, la lista de activas viene vacía.
    online = monitoring.workers_online()
    if not online:
        return ActiveTasksResponse(healthy=False, count=0)

    tareas = _aplanar_activas(monitoring.active_tasks())
    return ActiveTasksResponse(healthy=True, count=len(tareas), tasks=tareas)


@router.get("/scheduled", response_model=ScheduledTasksResponse)
def get_scheduled() -> ScheduledTasksResponse:
    """Tareas esperando su hora: acá se ven los REINTENTOS pendientes.

    Cuando una tarea de la Fase 1 falla, Celery la reencola con un countdown y
    queda acá hasta que le toca. El `eta` de cada entrada es el momento exacto
    del próximo intento: la diferencia contra ahora es el backoff que falta.
    """
    online = monitoring.workers_online()
    if not online:
        return ScheduledTasksResponse(healthy=False, count=0)

    tareas = _aplanar_agendadas(monitoring.scheduled_tasks())
    return ScheduledTasksResponse(healthy=True, count=len(tareas), tasks=tareas)


@router.get("/dashboard", response_model=DashboardResponse)
def get_dashboard() -> DashboardResponse:
    """Los números de una pantalla, en una sola pasada.

    Costo: hasta cuatro broadcasts con su timeout cada uno (`cluster_snapshot`
    corta en seco si no hay workers). NO es un endpoint para pollear cada 100ms
    desde un frontend: cada llamada despierta a todos los workers del cluster.
    """
    snapshot = monitoring.cluster_snapshot()

    # `count()` de la DLQ es un LLEN a Redis: O(1) y sin broadcast. Sale casi
    # gratis al lado del resto, y es el número que más rápido delata un
    # problema — si sube solo, algo se está rompiendo ahora.
    return DashboardResponse(
        healthy=snapshot["healthy"],
        workers_online=len(snapshot["workers"]),
        active=sum(len(t) for t in snapshot["active"].values()),
        reserved=sum(len(t) for t in snapshot["reserved"].values()),
        scheduled=sum(len(t) for t in snapshot["scheduled"].values()),
        dead_letter=dead_letter.count(),
    )
