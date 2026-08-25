import logging
import secrets
import time

from fastapi import HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader

from app.config import settings
from app.services.cache import redis_client

logger = logging.getLogger(__name__)

# auto_error=False deja el manejo del caso ausente a require_api_key.
# Declararlo asi hace aparecer el boton Authorize en /docs.
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(api_key: str | None = Security(_api_key_header)) -> None:
    """Exige la clave. Se monta sobre los routers de administracion."""
    if settings.is_dev and not settings.API_KEY:
        return

    # compare_digest y no ==: compara en tiempo constante.
    if api_key is None or not secrets.compare_digest(api_key, settings.API_KEY):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Unauthorized",
            headers={"WWW-Authenticate": "X-API-Key"},
        )


async def rate_limit(request: Request) -> None:
    """Ventana fija por IP, contada en Redis.

    El numero de ventana va en la clave: al cambiar de ventana la clave cambia
    y el contador arranca de cero sin borrar nada.
    """
    ventana = int(time.time()) // settings.RATE_LIMIT_WINDOW_SECONDS
    clave = f"ratelimit:{_client_ip(request)}:{ventana}"

    peticiones = await redis_client.incr(clave)
    if peticiones == 1:
        # Solo en la primera: repetirlo alargaria el TTL en cada peticion.
        await redis_client.expire(clave, settings.RATE_LIMIT_WINDOW_SECONDS)

    if peticiones > settings.RATE_LIMIT_REQUESTS:
        restante = await redis_client.ttl(clave)
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too Many Requests",
            headers={"Retry-After": str(max(restante, 1))},
        )


def _client_ip(request: Request) -> str:
    """IP del cliente.

    Detras de un proxy, request.client.host es el del proxy. Ahi hay que
    resolverlo con la config de proxies de confianza del servidor ASGI
    (uvicorn --forwarded-allow-ips), no leyendo cabeceras a mano.
    """
    return request.client.host if request.client else "desconocida"


def log_startup_mode() -> None:
    """Lo llama el lifespan al arrancar."""
    logger.info("ENVIRONMENT=%s", settings.ENVIRONMENT)
