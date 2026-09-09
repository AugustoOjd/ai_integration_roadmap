"""Lo único crítico del servicio de introspección: el cluster CAÍDO.

Es el caso que nunca ves en desarrollo (siempre tenés un worker levantado) y el
único que importa cuando el monitoreo se usa de verdad.
"""

from unittest.mock import MagicMock

import pytest

from app.services import monitoring


@pytest.mark.parametrize(
    "funcion",
    [
        monitoring.workers_online,
        monitoring.active_tasks,
        monitoring.reserved_tasks,
        monitoring.scheduled_tasks,
        monitoring.worker_stats,
    ],
)
def test_sin_workers_no_explota(funcion, monkeypatch):
    """`inspect()` devuelve None cuando NO CONTESTA NADIE, no un dict vacío.

    Sin normalizar, cualquier `for w in inspect.active()` revienta con
    TypeError — y revienta exactamente cuando el cluster se cayó, o sea cuando
    alguien está mirando el monitoreo con urgencia.
    """
    fake = MagicMock()
    for metodo in ("ping", "active", "reserved", "scheduled", "stats"):
        getattr(fake, metodo).return_value = None
    monkeypatch.setattr(monitoring, "_inspect", lambda: fake)

    assert funcion() in ({}, [])
