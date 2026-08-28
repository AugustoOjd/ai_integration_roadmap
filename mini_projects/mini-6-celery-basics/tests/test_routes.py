from unittest.mock import MagicMock

from app.routes import tasks as routes


def test_enqueue_devuelve_202_y_task_id(client, monkeypatch):
    # Parcheamos .delay: el test es del endpoint, no de Celery ni de Redis.
    monkeypatch.setattr(
        routes.slow_double, "delay", lambda _: MagicMock(id="abc-123", state="PENDING")
    )

    respuesta = client.post("/tasks/enqueue", json={"value": 21})

    # 202, no 200: aceptado pero todavía sin procesar.
    assert respuesta.status_code == 202
    assert respuesta.json() == {"task_id": "abc-123", "status": "PENDING"}


def test_enqueue_rechaza_valor_invalido(client):
    # ge=0 en el schema: la validación corta antes de gastar un slot del worker.
    assert client.post("/tasks/enqueue", json={"value": -1}).status_code == 422


def test_status_expone_ready(client, monkeypatch, fake_async_result):
    monkeypatch.setattr(
        routes, "AsyncResult", lambda task_id, app: fake_async_result("STARTED", ready=False)
    )

    cuerpo = client.get("/tasks/abc-123/status").json()

    assert cuerpo == {"task_id": "abc-123", "status": "STARTED", "ready": False}


def test_result_devuelve_202_si_no_terminó(client, monkeypatch, fake_async_result):
    """El punto del diseño: consultar no bloquea esperando a la tarea."""
    monkeypatch.setattr(
        routes, "AsyncResult", lambda task_id, app: fake_async_result("STARTED", ready=False)
    )

    respuesta = client.get("/tasks/abc-123/result")

    assert respuesta.status_code == 202
    assert respuesta.json()["result"] is None


def test_result_devuelve_200_con_el_valor(client, monkeypatch, fake_async_result):
    payload = {"task_id": "abc-123", "input": 21, "result": 42}
    monkeypatch.setattr(
        routes, "AsyncResult", lambda task_id, app: fake_async_result("SUCCESS", result=payload)
    )

    respuesta = client.get("/tasks/abc-123/result")

    assert respuesta.status_code == 200
    assert respuesta.json()["result"] == payload


def test_result_devuelve_500_si_la_tarea_falló(client, monkeypatch, fake_async_result):
    # En FAILURE, .result es la excepción que levantó la tarea.
    monkeypatch.setattr(
        routes,
        "AsyncResult",
        lambda task_id, app: fake_async_result(
            "FAILURE", failed=True, result=RuntimeError("boom")
        ),
    )

    respuesta = client.get("/tasks/abc-123/result")

    assert respuesta.status_code == 500
    assert "boom" in respuesta.json()["detail"]
