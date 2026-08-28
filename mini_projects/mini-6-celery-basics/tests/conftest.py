from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def fake_async_result():
    """Fábrica de AsyncResult falsos, para no depender de Redis en los tests.

    Los endpoints solo consultan el backend; falsear esa lectura deja el test
    sobre lo que de verdad estamos probando: los códigos de estado.
    """

    def _make(state: str, *, ready: bool = True, failed: bool = False, result=None):
        mock = MagicMock()
        mock.state = state
        mock.ready.return_value = ready
        mock.failed.return_value = failed
        mock.result = result
        return mock

    return _make
