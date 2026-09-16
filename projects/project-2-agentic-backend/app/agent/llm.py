from functools import lru_cache

from anthropic import Anthropic

from app.core.config import settings


@lru_cache(maxsize=1)
def get_client() -> Anthropic:
    """El cliente de Anthropic, creado una sola vez por proceso.

    El cliente envuelve un pool de conexiones HTTP: crearlo por request tira el
    pool y paga de nuevo el handshake TCP+TLS en cada llamada.

    `lru_cache(maxsize=1)` sobre una función sin argumentos difiere la
    construcción hasta el primer uso, así que importar el módulo en un test no
    instancia nada — que es lo que una variable de módulo no permite.

    La API key se pasa explícita aunque el SDK la leería sola de la variable de
    entorno: la fuente de verdad es `settings`, que además valida y falla al
    arrancar.
    """
    return Anthropic(
        api_key=settings.ANTHROPIC_API_KEY.get_secret_value(),
        timeout=settings.ANTHROPIC_TIMEOUT,
        # El SDK reintenta solo ante errores de conexión, 408, 409, 429 y 5xx con
        # backoff exponencial. El timeout es POR INTENTO: el tiempo de pared
        # máximo de una llamada es 30s x 3 = 90s, no 30s.
        max_retries=2,
    )
