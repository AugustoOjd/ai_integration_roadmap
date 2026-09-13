"""El endpoint del agente.

Envolver el loop en HTTP trae tensiones que no existen en un script:

  - LATENCIA. Un loop de tres vueltas son tres llamadas al modelo. Segundos, no
    milisegundos. El cliente necesita un timeout generoso, o streaming.
  - ERRORES AJENOS. El agente depende de un servicio de terceros que se cae, te
    limita y te rechaza requests. Cada uno de esos casos es un código HTTP
    distinto, y elegir mal le miente a quien te consume.
  - FUGAS. Todo lo que devolvés puede terminar en la pantalla de un usuario.
"""

import logging

from anthropic import (
    APIConnectionError,
    APIStatusError,
    AuthenticationError,
    BadRequestError,
    RateLimitError,
)
from fastapi import APIRouter, HTTPException, status

from app.agent import MaxIterationsError, run_agent
from app.schemas.agent import AgentRequest, AgentResponse, Usage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post(
    "/tool-calling",
    response_model=AgentResponse,
    summary="Ejecuta el agente con tool calling",
)
async def tool_calling(request: AgentRequest) -> AgentResponse:
    """Corre el agente y devuelve la respuesta final más su traza.

    Es `async def` y no `def` porque `run_agent` es una corrutina. Si fuera
    `def`, FastAPI lo correría en un threadpool y el `await` de adentro no
    tendría dónde ejecutarse.
    """
    try:
        result = await run_agent(request.prompt)

    # ------------------------------------------------------------ 429
    # Le estás pegando más rápido de lo que tu cuota permite. Es transitorio y
    # el cliente puede reintentar, así que se lo decimos con el mismo código
    # que nos dieron a nosotros.
    #
    # Ojo: el SDK YA reintentó dos veces con backoff antes de levantar esto. Si
    # llegó hasta acá, reintentar enseguida tampoco va a andar.
    except RateLimitError as exc:
        # `retry-after` viene en la respuesta de la API. Reenviarlo convierte un
        # "probá más tarde" en un "probá en 12 segundos", que es la diferencia
        # entre un cliente que espera y uno que martilla.
        retry_after = exc.response.headers.get("retry-after")
        logger.warning("rate limit de la API (retry-after=%s)", retry_after)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="El servicio está saturado. Reintentá en unos segundos.",
            headers={"Retry-After": retry_after} if retry_after else None,
        ) from exc

    # ------------------------------------------------------------ 500
    # Credenciales mal configuradas. Es un problema TUYO, de deploy, y el
    # cliente no puede hacer nada al respecto: 500, no 401.
    #
    # Devolver 401 acá sería el error clásico de traducir el código del
    # proveedor uno a uno: le diría al cliente "tus credenciales están mal"
    # cuando las que están mal son las del servidor.
    except AuthenticationError as exc:
        logger.error("credenciales de Anthropic inválidas o ausentes")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error de configuración del servicio.",
        ) from exc

    # ------------------------------------------------------------ 500
    # Un 400 de la API es un request mal armado, y el request lo armamos
    # NOSOTROS: un `tool_use` sin su result, un schema inválido, un parámetro
    # que el modelo no soporta. Es un bug del servidor.
    #
    # El prompt del cliente ya lo validó Pydantic antes de llegar acá.
    except BadRequestError as exc:
        logger.exception("request inválido hacia la API")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno al construir la consulta.",
        ) from exc

    # ------------------------------------------------------------ 502
    # Cualquier otro error con código HTTP de la API (500, 529, ...). Somos un
    # gateway hacia un upstream que falló: eso es exactamente un 502.
    #
    # Va DESPUÉS de los tres anteriores porque es su clase padre: en una cadena
    # de `except`, gana el primero que matchea, así que lo general va al final.
    except APIStatusError as exc:
        logger.error("la API respondió %s", exc.status_code)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="El proveedor del modelo devolvió un error.",
        ) from exc

    # ------------------------------------------------------------ 503
    # No pudimos ni hablar con la API: red caída, DNS, timeout. Nada llegó.
    # `APITimeoutError` es subclase de esta, así que queda cubierto.
    #
    # 503 y no 502 porque 502 dice "el upstream contestó mal" y acá el upstream
    # no contestó nada.
    except APIConnectionError as exc:
        logger.error("no se pudo contactar a la API: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No se pudo contactar al proveedor del modelo.",
        ) from exc

    # ------------------------------------------------------------ 422
    # El agente no convergió. No falló nadie: ni el cliente mandó algo
    # inválido, ni el proveedor se cayó. La tarea, tal como está planteada, no
    # se pudo resolver con las tools disponibles.
    #
    # 422 ("entendí el request, no lo puedo procesar") es lo más honesto que
    # hay para eso.
    except MaxIterationsError as exc:
        logger.warning("no convergió: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El agente no pudo resolver la consulta. Probá reformularla.",
        ) from exc

    # Una línea de log por corrida exitosa, con lo que vas a querer agregar
    # después: cuántas vueltas, qué tools, cuántos tokens. Es de donde salen los
    # dashboards de costo cuando esto crece.
    logger.info(
        "ok iterations=%d tools=%s in=%d out=%d",
        result.iterations,
        result.tools_used,
        result.input_tokens,
        result.output_tokens,
    )

    return AgentResponse(
        prompt=request.prompt,
        final_answer=result.text,
        tools_used=result.tools_used,
        iterations=result.iterations,
        usage=Usage(
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        ),
    )
