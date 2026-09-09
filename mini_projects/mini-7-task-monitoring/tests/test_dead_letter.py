"""Lo mínimo de la DLQ: que guarde lo necesario y que no pierda tareas.

Se parchea el cliente de Redis: lo que hay que verificar es QUÉ comandos
mandamos y con qué datos, no que Redis funcione.
"""

import json
from unittest.mock import MagicMock

import pytest

from app.config import settings
from app.exceptions import PermanentError
from app.services import dead_letter


@pytest.fixture
def redis_falso(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(dead_letter, "_client", fake)
    return fake


def test_guarda_lo_necesario_para_reprocesar(redis_falso):
    """Sin `task_name` + `args` + `kwargs`, la DLQ es un log caro: sabés que
    algo falló pero no podés reencolarlo. Es la diferencia entre recuperar
    3.000 operaciones perdidas y no poder hacer nada.

    El LTRIM va en el mismo test porque es el guard contra una fuga de memoria
    silenciosa: sin él, una tarea que falla en bucle llena Redis.
    """
    dead_letter.record_failure(
        task_id="t-1",
        task_name="tasks.fetch_resource",
        args=("doc-1", 404),
        kwargs={"extra": True},
        exception=PermanentError("boom"),
        retries=0,
    )

    pipe = redis_falso.pipeline.return_value
    _key, payload = pipe.lpush.call_args.args
    entrada = json.loads(payload)

    assert entrada["task_name"] == "tasks.fetch_resource"
    assert entrada["args"] == ["doc-1", 404]
    assert entrada["kwargs"] == {"extra": True}
    # El TIPO, no solo el mensaje: es lo que separa "hay que arreglar el código"
    # de "el proveedor estuvo caído".
    assert entrada["exc_type"] == "PermanentError"
    assert entrada["retries"] == 0

    pipe.ltrim.assert_called_once_with(
        settings.DEAD_LETTER_KEY, 0, settings.DEAD_LETTER_MAX - 1
    )


def test_replay_encola_antes_de_borrar(redis_falso, monkeypatch):
    """El único lugar del proyecto donde un orden mal puesto PIERDE trabajo.

    Encolar y después borrar: si el proceso muere en el medio, la tarea se
    duplica (recuperable, porque son idempotentes). Al revés, se pierde para
    siempre.
    """
    from app.celery_app import celery_app

    raw = json.dumps({"task_name": "tasks.fetch_resource", "args": ["doc-1"], "kwargs": {}})
    redis_falso.lrange.return_value = [raw]

    orden: list[str] = []
    monkeypatch.setattr(
        celery_app, "send_task", lambda name, args, kwargs: orden.append("encolar")
    )
    redis_falso.lrem.side_effect = lambda *a: orden.append("borrar")

    assert dead_letter.replay() == 1
    assert orden == ["encolar", "borrar"]
    # Borra la entrada EXACTA que reenvió, no "una cualquiera".
    redis_falso.lrem.assert_called_once_with(settings.DEAD_LETTER_KEY, 1, raw)
