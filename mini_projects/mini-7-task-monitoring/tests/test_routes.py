"""Lo mínimo de los endpoints: contratos que un cliente ya depende.

Todo lo de atrás (Celery, Redis, workers) va parcheado. Acá se prueba lo que
rompería a un frontend sin que se rompa ningún test de backend.
"""

from unittest.mock import MagicMock

from app.routes import monitoring as rutas_monitoring
from app.routes import tasks as rutas_tasks


def test_encolar_devuelve_202_y_task_id(client, monkeypatch):
    """El contrato entero de una API con tareas: 202 + un id para consultar.

    Si esto se convierte en 200, o desaparece el task_id, el cliente pierde la
    única forma que tiene de seguir la tarea.
    """
    monkeypatch.setattr(
        rutas_tasks.flaky, "delay", lambda _: MagicMock(id="abc-123", state="PENDING")
    )

    respuesta = client.post("/tasks/flaky", json={"fail_times": 2})

    assert respuesta.status_code == 202
    assert respuesta.json() == {"task_id": "abc-123", "status": "PENDING"}


def test_valida_antes_de_encolar(client):
    # La validación corta ANTES de gastar un slot del worker: una tarea
    # inválida no debería llegar a la cola.
    assert client.post("/tasks/flaky", json={"fail_times": 99}).status_code == 422


def test_progress_traduce_segun_el_estado(client, monkeypatch, fake_async_result):
    """`info` guarda cosas de NATURALEZA distinta según el estado: un dict de
    progreso, un valor de retorno o una EXCEPCIÓN.

    Leerlo sin mirar el estado es un TypeError en producción. Este test fija
    las dos ramas que se confunden.
    """
    monkeypatch.setattr(
        rutas_tasks,
        "AsyncResult",
        lambda task_id, app: fake_async_result("PROGRESS", info={"current": 30, "total": 40}),
    )
    assert client.get("/tasks/abc/progress").json()["percent"] == 75

    monkeypatch.setattr(
        rutas_tasks,
        "AsyncResult",
        lambda task_id, app: fake_async_result("FAILURE", info=RuntimeError("boom")),
    )
    cuerpo = client.get("/tasks/abc/progress").json()
    assert cuerpo["percent"] is None
    assert "boom" in cuerpo["detail"]


def test_revoke_no_mata_procesos_por_default(client, monkeypatch):
    """`terminate=True` mata el proceso hijo sin cleanup: `finally` no corre,
    las escrituras a medias quedan a medias. Que sea opt-in es una decisión de
    seguridad, y un default invertido no falla ningún otro test."""
    llamadas = []
    monkeypatch.setattr(
        rutas_tasks.task_control, "revoke", lambda task_id, terminate: llamadas.append(terminate)
    )
    monkeypatch.setattr(rutas_tasks.task_control, "state_of", lambda _: "PENDING")

    client.delete("/tasks/abc-123")
    client.delete("/tasks/abc-123?terminate=true")

    assert llamadas == [False, True]


def test_monitoreo_responde_200_con_el_cluster_caido(client, monkeypatch):
    """La regla de oro: un endpoint de monitoreo no se cae cuando el sistema se
    cae. Es justo cuando alguien lo está mirando.

    Con 503, el cliente no puede distinguir "el cluster está caído" de "el
    endpoint de monitoreo está roto".
    """
    monkeypatch.setattr(rutas_monitoring.monitoring, "workers_online", lambda: [])
    monkeypatch.setattr(rutas_monitoring.monitoring, "worker_stats", lambda: {})
    monkeypatch.setattr(
        rutas_monitoring.monitoring,
        "cluster_snapshot",
        lambda: {
            "healthy": False,
            "workers": [],
            "active": {},
            "reserved": {},
            "scheduled": {},
            "stats": {},
        },
    )
    monkeypatch.setattr(rutas_monitoring.dead_letter, "count", lambda: 0)

    for ruta in ("/monitoring/workers", "/monitoring/active", "/monitoring/dashboard"):
        respuesta = client.get(ruta)
        assert respuesta.status_code == 200, ruta
        assert respuesta.json()["healthy"] is False, ruta
