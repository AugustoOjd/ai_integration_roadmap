from functools import lru_cache

from anthropic import Anthropic

from app.config import settings


@lru_cache(maxsize=1)
def get_client() -> Anthropic:
    """El cliente de Anthropic, creado una sola vez por proceso.

    Por qué un singleton y no un `Anthropic()` nuevo por request: el cliente es
    un wrapper sobre un pool de conexiones HTTP. Crearlo por request tira el
    pool a la basura cada vez, y cada llamada paga de nuevo el handshake TCP +
    TLS contra la API. Es el mismo razonamiento que con un pool de conexiones a
    la base de datos.

    `lru_cache(maxsize=1)` sobre una función sin argumentos es el modismo de
    Python para "creá esto la primera vez que alguien lo pida, y devolvé siempre
    el mismo". Se prefiere a una variable de módulo (`client = Anthropic()`)
    porque difiere la construcción: el módulo se puede importar en un test sin
    que se instancie nada.

    Nota sobre la API key: el SDK la lee solo de ANTHROPIC_API_KEY si no se la
    pasás. Se la pasamos explícitamente igual, porque queremos que la fuente de
    verdad sea `settings` — el mismo lugar que valida, documenta y falla rápido
    para todo lo demás. Dos caminos distintos para leer la misma credencial es
    exactamente el tipo de ambigüedad que después cuesta una tarde de debug.
    """
    return Anthropic(
        api_key=settings.ANTHROPIC_API_KEY.get_secret_value(),
        timeout=settings.ANTHROPIC_TIMEOUT,
        # El SDK reintenta solo ante errores de conexión, 408, 409, 429 y 5xx,
        # con backoff exponencial. Son fallos transitorios: la misma lógica del
        # mini 7, pero acá ya viene resuelta y no hay que escribirla.
        #
        # El default son 2 reintentos y lo dejamos. Ojo con la cuenta que casi
        # nadie hace: el timeout es POR INTENTO, así que el tiempo de pared
        # máximo de una llamada es 30s x 3 = 90s, no 30s.
        max_retries=2,
    )
