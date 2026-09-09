"""Lo mínimo que hay que probar de una tarea de Celery.

El problema: una tarea con backoff espera 2s, 4s, 8s, y ningún test puede
esperar eso. La salida es parchear `self.retry` — `self` dentro de una tarea ES
el objeto de la tarea— y observar la DECISIÓN de reintentar sin que ocurra la
espera.

Lo que NO se prueba acá: que Celery reintente (es su trabajo, ya está testeado),
ni los valores del decorador (espejar la config no atrapa errores). Se prueba
que NUESTRAS excepciones caigan del lado correcto de la política.
"""

import pytest

from app import tasks
from app.base_task import DeadLetterTask
from app.exceptions import PermanentError, TransientError


class SeñalDeRetry(Exception):
    """Reemplaza a la excepción Retry de Celery: marca "pidió reintentar"."""


@pytest.fixture
def espiar_retry(monkeypatch):
    """Intercepta .retry() de una tarea y devuelve las excepciones vistas."""

    def _espiar(tarea) -> list[BaseException]:
        vistas: list[BaseException] = []

        def fake_retry(exc=None, **kwargs):
            vistas.append(exc)
            raise SeñalDeRetry

        monkeypatch.setattr(tarea, "retry", fake_retry)
        return vistas

    return _espiar


def test_reintenta_lo_transitorio(espiar_retry):
    vistas = espiar_retry(tasks.fetch_resource)

    with pytest.raises(SeñalDeRetry):
        tasks.fetch_resource.run("doc-1", 503)

    assert isinstance(vistas[0], TransientError)


def test_NO_reintenta_lo_permanente(espiar_retry):
    """El test que justifica la taxonomía de excepciones.

    Lo importante es el `vistas == []`: no se pidió reintentar NI UNA vez. Si
    esto se rompe, nada falla ruidosamente — solo empezás a gastar 4 slots del
    worker por cada request inválido.
    """
    vistas = espiar_retry(tasks.fetch_resource)

    with pytest.raises(PermanentError):
        tasks.fetch_resource.run("doc-1", 404)

    assert vistas == []


@pytest.mark.parametrize("tarea", [tasks.flaky, tasks.fetch_resource, tasks.process_batch])
def test_toda_tarea_registra_sus_fallos(tarea):
    """Olvidarse de `base=DeadLetterTask` en una tarea nueva es fácil, y el
    síntoma es invisible: los fallos de esa tarea no quedan en ningún lado."""
    assert isinstance(tarea, DeadLetterTask)


@pytest.mark.parametrize("total", [3, 40, 1000])
def test_progreso_acotado_y_completo(total, monkeypatch):
    """Dos garantías en un test, las dos con fallas silenciosas:

    1. El último reporte SIEMPRE llega al total. Sin eso, una barra de progreso
       se queda clavada en 95% hasta que la tarea termina de golpe.
    2. La cantidad de reportes está acotada. Cada uno es una escritura a Redis:
       sin techo, una tarea de 100.000 ítems satura el backend de TODO el
       sistema, no solo el suyo.

    El caso total=3 cubre el borde del `max(1, ...)`: sin él, el paso sería 0 y
    el módulo revienta con ZeroDivisionError.
    """
    monkeypatch.setattr(tasks.time, "sleep", lambda _: None)
    reportes: list[dict] = []
    monkeypatch.setattr(
        tasks.process_batch, "update_state", lambda state, meta: reportes.append(meta)
    )

    tasks.process_batch.run(total)

    assert reportes[-1] == {"current": total, "total": total}
    assert len(reportes) <= tasks.MAX_REPORTES_DE_PROGRESO
