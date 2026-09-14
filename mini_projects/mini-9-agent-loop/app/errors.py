"""Traducción de errores de dominio a códigos HTTP, en un solo lugar.

En el mini 8 esto era una cadena de `except` dentro del único endpoint. Con
varios endpoints —y en la Fase 6 van a ser cuatro— esa cadena se copia y se
desincroniza: alguien agrega un `except` en uno y se olvida en los otros, y la
misma falla devuelve 502 acá y 500 allá.

Los *exception handlers* de FastAPI resuelven eso: se registran una vez sobre la
app, y cualquier excepción que se escape de cualquier ruta cae en el handler que
le corresponde. Las rutas quedan escritas como si nada pudiera fallar, que es
como se leen bien.

El criterio para elegir el código es siempre el mismo pregunta: **¿de quién es
el problema?** Del cliente (4xx), tuyo (5xx), o de un tercero del que dependés
(502/503). Traducir el código del proveedor uno a uno es el error clásico: un
401 de Anthropic no es un 401 para tu cliente — tus credenciales no son las
suyas.
"""

import logging

from anthropic import (
    APIConnectionError,
    APIStatusError,
    AuthenticationError,
    BadRequestError,
    RateLimitError,
)
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.agent import ApprovalRequired, MaxIterationsError
from app.budget import BudgetExceededError
from app.repository import (
    ApprovalAlreadyDecidedError,
    ApprovalExpiredError,
    ApprovalNotFoundError,
    SessionNotFoundError,
    SessionPausedError,
)
from app.schemas.sessions import PendingApprovalBody, PendingApprovalResponse

logger = logging.getLogger(__name__)


def _json(code: int, detail: str, headers: dict[str, str] | None = None) -> JSONResponse:
    """Misma forma de body que usa el `HTTPException` de FastAPI.

    Importa que sea la misma: un cliente no debería tener que parsear dos
    formatos de error según qué salió mal.
    """
    return JSONResponse(status_code=code, content={"detail": detail}, headers=headers)


def install_error_handlers(app: FastAPI) -> None:
    """Registra la traducción completa. Se llama una vez, al crear la app."""

    # ---------------------------------------------------------------- 404
    # Error de dominio propio. Que el repositorio levante una excepción en vez
    # de devolver `None` es lo que permite decidir el código HTTP acá arriba,
    # con toda la información, en vez de que cada ruta adivine qué significaba
    # ese `None` que le llegó de tres capas más abajo.
    @app.exception_handler(SessionNotFoundError)
    async def _sesion_no_existe(request: Request, exc: SessionNotFoundError) -> JSONResponse:
        return _json(status.HTTP_404_NOT_FOUND, "La sesión no existe.")

    # ---------------------------------------------------------------- 202
    # No es un error: el loop se frenó esperando que un humano autorice una tool
    # sensible. El request se aceptó, el trabajo no terminó, y hay otro recurso
    # donde seguirlo. Eso es exactamente un 202 Accepted.
    #
    # No es 4xx (nadie hizo nada mal) ni 200 (no hay respuesta del agente
    # todavía). Devolver 200 con un flag sería lo más fácil y lo peor: un
    # cliente que no mira el flag trataría un pedido de permiso como una
    # respuesta, y el código de estado está justamente para no depender de que
    # el cliente lea bien el body.
    @app.exception_handler(ApprovalRequired)
    async def _requiere_aprobacion(request: Request, exc: ApprovalRequired) -> JSONResponse:
        logger.info(
            "202 pendiente de aprobación session=%s tools=%s",
            exc.session_id,
            [a.tool_name for a in exc.aprobaciones],
        )
        cuerpo = PendingApprovalBody(
            session_id=exc.session_id,
            pending=[PendingApprovalResponse.model_validate(a) for a in exc.aprobaciones],
        )
        # `mode="json"` convierte los `datetime` a ISO 8601. Sin eso,
        # `JSONResponse` intenta serializar un objeto que el encoder estándar no
        # conoce y falla.
        return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=cuerpo.model_dump(mode="json"))

    # ---------------------------------------------------------------- 409
    # Llegó un mensaje nuevo a una sesión que está esperando una decisión.
    #
    # 409 Conflict es el código de "tu pedido es válido, pero choca con el
    # estado actual del recurso". La resolución no es reintentar: es resolver lo
    # pendiente primero.
    #
    # Sin esto, el segundo mensaje arrancaría un turno nuevo sobre un historial
    # que tiene un `tool_use` sin cerrar, y la API lo rechazaría con un 400
    # incomprensible.
    @app.exception_handler(SessionPausedError)
    async def _sesion_pausada(request: Request, exc: SessionPausedError) -> JSONResponse:
        return _json(
            status.HTTP_409_CONFLICT,
            "La sesión está esperando una aprobación. Resolvé lo pendiente antes "
            "de mandar otro mensaje.",
        )

    # ---------------------------------------------------------------- 404
    @app.exception_handler(ApprovalNotFoundError)
    async def _aprobacion_no_existe(
        request: Request, exc: ApprovalNotFoundError
    ) -> JSONResponse:
        return _json(status.HTTP_404_NOT_FOUND, "No hay ninguna aprobación pendiente con ese id.")

    # ---------------------------------------------------------------- 409
    # Idempotencia. El segundo POST con el mismo `tool_use_id` no ejecuta la
    # tool de nuevo: la corta acá. "De nuevo" significa una segunda cancelación,
    # un segundo mail, un segundo reembolso.
    #
    # 409 y no 200-silencioso: el cliente tiene que poder distinguir "tu
    # decisión se aplicó" de "alguien ya había decidido esto". Si el segundo
    # POST devolviera 200, un botón con doble click reportaría dos éxitos donde
    # hubo una sola acción.
    @app.exception_handler(ApprovalAlreadyDecidedError)
    async def _ya_decidida(request: Request, exc: ApprovalAlreadyDecidedError) -> JSONResponse:
        return _json(status.HTTP_409_CONFLICT, "Esa aprobación ya fue decidida.")

    # ---------------------------------------------------------------- 409
    @app.exception_handler(ApprovalExpiredError)
    async def _vencida(request: Request, exc: ApprovalExpiredError) -> JSONResponse:
        return _json(
            status.HTTP_409_CONFLICT,
            "El pedido de aprobación venció. Pedile al agente que lo proponga de nuevo.",
        )

    # ---------------------------------------------------------------- 422
    # El agente no convergió. No falló nadie: ni el cliente mandó algo inválido
    # ni el proveedor se cayó. La tarea, tal como está planteada, no se pudo
    # resolver con las tools disponibles.
    @app.exception_handler(MaxIterationsError)
    async def _no_convergio(request: Request, exc: MaxIterationsError) -> JSONResponse:
        logger.warning("no convergió: %s", exc)
        return _json(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "El agente no pudo resolver la consulta. Probá reformularla.",
        )

    # ---------------------------------------------------------------- 402
    # Se acabó el presupuesto de la sesión.
    #
    # 402 Payment Required es el código menos usado de HTTP y justamente éste es
    # su caso: el request es válido, el servicio anda, y no se atiende por una
    # cuestión de cuota. Las alternativas son peores: 429 diría "vas muy rápido,
    # esperá" y acá esperar no sirve de nada; 403 diría "no tenés permiso", y
    # permiso hay.
    #
    # Los números van en el body porque un "sin presupuesto" a secas obliga a
    # quien lo recibe a adivinar si le faltan 100 tokens o 100.000.
    @app.exception_handler(BudgetExceededError)
    async def _sin_presupuesto(request: Request, exc: BudgetExceededError) -> JSONResponse:
        logger.warning("presupuesto agotado: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            content={
                "detail": "La sesión se quedó sin presupuesto de tokens.",
                "tokens_necesarios": exc.necesarios,
                "tokens_disponibles": exc.disponibles,
            },
        )

    # ---------------------------------------------------------------- 429
    # Le estás pegando más rápido de lo que tu cuota permite. Es transitorio.
    #
    # Ojo: el SDK YA reintentó con backoff antes de levantar esto. Si llegó
    # hasta acá, reintentar enseguida tampoco va a andar — por eso el
    # `Retry-After`, que convierte un "probá más tarde" en un "probá en 12
    # segundos".
    @app.exception_handler(RateLimitError)
    async def _rate_limit(request: Request, exc: RateLimitError) -> JSONResponse:
        retry_after = exc.response.headers.get("retry-after")
        logger.warning("rate limit de la API (retry-after=%s)", retry_after)
        return _json(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "El servicio está saturado. Reintentá en unos segundos.",
            headers={"Retry-After": retry_after} if retry_after else None,
        )

    # ---------------------------------------------------------------- 500
    # Credenciales mal configuradas: es un problema TUYO, de deploy, y el
    # cliente no puede hacer nada. Devolver 401 acá le diría "tus credenciales
    # están mal" cuando las que están mal son las del servidor.
    @app.exception_handler(AuthenticationError)
    async def _auth(request: Request, exc: AuthenticationError) -> JSONResponse:
        logger.error("credenciales de Anthropic inválidas o ausentes")
        return _json(status.HTTP_500_INTERNAL_SERVER_ERROR, "Error de configuración del servicio.")

    # ---------------------------------------------------------------- 500
    # Un 400 de la API es un request mal armado, y el request lo armamos
    # NOSOTROS. En este mini el sospechoso número uno tiene nombre: un
    # `tool_use` sin su `tool_result`, o sea la persistencia de la Fase 1 o el
    # recorte de la Fase 8 partiendo un par.
    @app.exception_handler(BadRequestError)
    async def _bad_request(request: Request, exc: BadRequestError) -> JSONResponse:
        logger.exception("request inválido hacia la API")
        return _json(status.HTTP_500_INTERNAL_SERVER_ERROR, "Error interno al construir la consulta.")

    # ---------------------------------------------------------------- 502
    # Cualquier otro error CON código HTTP de la API (500, 529...). Somos un
    # gateway hacia un upstream que falló: eso es exactamente un 502.
    #
    # Es la clase padre de los tres anteriores. En los handlers de FastAPI el
    # despacho es por la clase más específica, así que el orden de registro no
    # importa (a diferencia de una cadena de `except`, donde sí).
    @app.exception_handler(APIStatusError)
    async def _api_status(request: Request, exc: APIStatusError) -> JSONResponse:
        logger.error("la API respondió %s", exc.status_code)
        return _json(status.HTTP_502_BAD_GATEWAY, "El proveedor del modelo devolvió un error.")

    # ---------------------------------------------------------------- 503
    # No pudimos ni hablar con la API: red, DNS, timeout (`APITimeoutError` es
    # subclase de ésta). 503 y no 502 porque 502 dice "el upstream contestó
    # mal", y acá el upstream no contestó nada.
    @app.exception_handler(APIConnectionError)
    async def _sin_conexion(request: Request, exc: APIConnectionError) -> JSONResponse:
        logger.error("no se pudo contactar a la API: %s", exc)
        return _json(
            status.HTTP_503_SERVICE_UNAVAILABLE, "No se pudo contactar al proveedor del modelo."
        )
