"""Fixtures compartidas.

Ningún test de este proyecto necesita Redis, ni un worker, ni esperar un
backoff. Eso es una decisión de diseño, no una limitación: la lógica vive en
funciones puras (`services/`) y lo que queda en las tareas es orquestación, que
se verifica parcheando lo que Celery haría.
"""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def fake_async_result():
    """Fábrica de AsyncResult falsos.

    Los endpoints solo LEEN el backend. Falsear esa lectura deja el test sobre
    lo que de verdad se está probando: la traducción de estados a respuestas
    HTTP, que es donde está toda la lógica del endpoint.
    """

    def _make(state: str, *, info=None, result=None, ready: bool | None = None):
        mock = MagicMock()
        mock.state = state
        mock.info = info
        mock.result = result
        # Por default, ready() se deduce del estado: los READY de Celery son
        # exactamente estos tres.
        mock.ready.return_value = (
            ready if ready is not None else state in ("SUCCESS", "FAILURE", "REVOKED")
        )
        return mock

    return _make
