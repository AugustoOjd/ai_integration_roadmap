"""La política de reintentos: qué error se reintenta y cuál no.

Es lógica pura, sin Celery. Los tests más baratos del proyecto y los que más
plata protegen: cada error mal clasificado son 4 ejecuciones desperdiciadas o
una tarea que se pierde sin reintentar.
"""

import pytest

from app.exceptions import PermanentError, TaskError, TransientError
from app.services.external_api import fetch


# 429 es el caso que rompe la regla intuitiva de "4xx no se reintenta": el
# request está bien, solo llegó demasiado seguido. Es el error más común contra
# APIs de LLM. El 599 cubre la regla "5xx desconocido → el problema es de ellos".
@pytest.mark.parametrize("status", [429, 503, 599])
def test_se_reintenta_lo_transitorio(status):
    with pytest.raises(TransientError):
        fetch("doc-1", status)


@pytest.mark.parametrize("status", [400, 404, 418])
def test_no_se_reintenta_lo_permanente(status):
    with pytest.raises(PermanentError):
        fetch("doc-1", status)


def test_permanente_no_hereda_de_transitorio():
    """La invariante que sostiene TODA la política de reintentos.

    `autoretry_for` matchea por HERENCIA. Si alguien hiciera que PermanentError
    heredara de TransientError, los errores permanentes empezarían a
    reintentarse y nadie se enteraría hasta ver la factura del proveedor. Una
    línea que protege el diseño entero.
    """
    assert not issubclass(PermanentError, TransientError)
    assert issubclass(PermanentError, TaskError)
