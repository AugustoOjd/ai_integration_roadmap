"""Qué se reintenta y qué no.

La mitad fácil de los reintentos ya la trae Celery. La que importa es ésta, y la
regla que la ordena es una sola:

    se reintenta lo que depende del MUNDO, no lo que depende de TU ESTADO.

Un `BudgetExceededError` se va a agotar igual las tres veces, tres veces más caro
si alguna llegó a llamar al modelo. Un `APIConnectionError` no: el mundo se cayó
un segundo y se levantó.

    reintentable               permanente
    ------------------------   ---------------------------
    APIConnectionError         BudgetExceededError
    APITimeoutError            MaxIterationsError
    InternalServerError (5xx)  BadRequestError (400)
    RateLimitError (429)       AuthenticationError (401)
    OperationalError (la BD)   input de tool inválido
"""

import random

from anthropic import (
    APIConnectionError,
    InternalServerError,
    RateLimitError,
)
from sqlalchemy.exc import OperationalError

# Una allowlist, igual que en el evaluador de `calculate`: lo que no está acá se
# trata como permanente. El default es "no reintentar", así que un error nuevo
# que nadie clasificó falla rápido en vez de gastar tres veces.
#
# APIConnectionError incluye APITimeoutError, que es su subclase.
# InternalServerError es el 5xx del proveedor; NO se usa APIStatusError porque es
# el padre de todos los códigos, 400 y 401 incluidos.
REINTENTABLES: tuple[type[Exception], ...] = (
    APIConnectionError,
    InternalServerError,
    RateLimitError,
    OperationalError,
)

MAX_REINTENTOS = 3
ESPERA_BASE_S = 1.0
ESPERA_MAX_S = 60.0


def es_reintentable(exc: BaseException) -> bool:
    return isinstance(exc, REINTENTABLES)


def espera(exc: BaseException, intento: int) -> float:
    """Cuántos segundos esperar antes del próximo intento.

    `intento` es cuántos reintentos ya se consumieron (0 en el primer fallo).

    Para un rate limit NO se usa este backoff: la respuesta trae un header
    `retry-after` con el tiempo real que el proveedor pide. Tu exponencial es una
    adivinanza; ese número no lo es.
    """
    if isinstance(exc, RateLimitError):
        pedido = _retry_after(exc)
        if pedido is not None:
            return pedido

    exponencial = min(ESPERA_BASE_S * 2**intento, ESPERA_MAX_S)

    # El jitter no es cosmético. Sin él, diez tareas que fallan juntas por un
    # mismo incidente reintentan EXACTAMENTE a la vez, tres veces seguidas: es un
    # ataque de denegación de servicio contra tu propio proveedor, y contra vos
    # cuando el que se cayó es Postgres.
    #
    # "Full jitter" a medias: se conserva la mitad del backoff y se reparte la
    # otra al azar, así la espera nunca colapsa a casi cero.
    return exponencial * (0.5 + random.random() / 2)


def _retry_after(exc: RateLimitError) -> float | None:
    """El `retry-after` de la respuesta, si vino y si es un número de segundos."""
    respuesta = getattr(exc, "response", None)
    if respuesta is None:
        return None
    crudo = respuesta.headers.get("retry-after")
    if not crudo:
        return None
    try:
        # El header también admite una fecha HTTP; si no parsea como número, se
        # cae al backoff propio en vez de inventar.
        return float(crudo)
    except ValueError:
        return None
