"""Simulación de un cliente HTTP contra un servicio externo.

Acá no hay Celery. Es a propósito: la traducción "qué me devolvió el mundo" →
"qué tipo de error es esto" es lógica de negocio pura, testeable sin broker, sin
worker y sin esperar un solo segundo de backoff (Fase 8).

La tarea de Celery encima de esto termina teniendo tres líneas.
"""

from app.exceptions import PermanentError, TransientError

# Códigos que, por definición del protocolo, significan "volvé a intentar":
#   408 Request Timeout      → la request no llegó a tiempo
#   425 Too Early            → el server pide que reintentes
#   429 Too Many Requests    → rate limit; el caso más común contra APIs de LLM
#   500 Internal Server Error
#   502 Bad Gateway          → un proxy no pudo hablar con el upstream
#   503 Service Unavailable  → sobrecarga o mantenimiento, explícitamente temporal
#   504 Gateway Timeout
RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


def _classify(status: int) -> TransientError | PermanentError:
    """Traduce un status HTTP a nuestra taxonomía.

    Devuelve la excepción en vez de levantarla para que el que llama escriba
    `raise _classify(...)`: así queda a la vista que ahí termina el flujo.
    """
    if status in RETRYABLE_STATUS:
        return TransientError(f"El servicio externo respondió {status}, reintentable")

    # 5xx que no está en la lista: el server falló por su cuenta. No sabemos por
    # qué, pero el problema es de ellos y puede resolverse solo → transitorio.
    if status >= 500:
        return TransientError(f"Error {status} del servidor, reintentable")

    # 4xx: el server dice que el problema está en NUESTRA request. Mandar la
    # misma request de nuevo da el mismo 4xx. Reintentar es puro desperdicio.
    return PermanentError(f"El servicio externo respondió {status}, no reintentable")


def fetch(resource_id: str, simulated_status: int = 200) -> dict:
    """Simula `GET /recursos/{resource_id}` contra un servicio externo.

    `simulated_status` reemplaza a la red: en el mundo real sería
    `response.status_code`. Nos deja provocar cada rama a voluntad.
    """
    if simulated_status == 200:
        return {"resource_id": resource_id, "payload": f"contenido de {resource_id}"}

    raise _classify(simulated_status)
