import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.schemas.chat import ChatRequest, ChatResponse, Source
from app.services import cache
from app.services.llm import LLMError
from app.services.rag import answer, answer_stream

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(payload: ChatRequest, response: Response, db: AsyncSession = Depends(get_db)):
    """Pipeline RAG completo: recuperar, ensamblar contexto, generar."""
    # Solo se cachean las preguntas SIN historial: con conversacion detras, la
    # misma frase significa cosas distintas ("y cuantos tiene?").
    cacheable = not payload.history

    if cacheable and (guardado := await cache.get_answer(payload.query, settings.TOP_K)):
        logger.info("CACHE HIT  -> %r", payload.query)
        # Cabecera de diagnostico: permite ver el hit sin mirar los logs.
        response.headers["X-Cache"] = "HIT"
        return ChatResponse.model_validate_json(guardado)

    try:
        resultado = await answer(
            db,
            payload.query,
            # model_dump ya trae solo role y content, y el historial viene
            # recortado por el validador del schema.
            history=[m.model_dump() for m in payload.history],
        )
    except LLMError as exc:
        # 502: el fallo es del proveedor, no de la peticion del cliente.
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "LLM no disponible") from exc

    respuesta = ChatResponse(
        answer=resultado.text,
        sources=[
            Source(n=n, source=hit.source, page=hit.page, similarity=hit.similarity)
            for n, hit in enumerate(resultado.sources, start=1)
        ],
    )

    if cacheable:
        logger.info("CACHE MISS -> %r (ttl=%ds)", payload.query, settings.CACHE_TTL_SECONDS)
        await cache.set_answer(payload.query, settings.TOP_K, respuesta.model_dump_json())
        response.headers["X-Cache"] = "MISS"

    return respuesta


def _sse(tipo: str, **datos) -> str:
    """Un evento Server-Sent Events.

    El formato lo fija la especificacion: `data: <carga>` y una linea en blanco
    que marca el fin del evento. El JSON va en una sola linea porque un salto
    dentro de la carga cortaria el evento.
    """
    return f"data: {json.dumps({'type': tipo, **datos}, ensure_ascii=False)}\n\n"


@router.post("/stream")
async def chat_stream(payload: ChatRequest, db: AsyncSession = Depends(get_db)):
    """Igual que /chat pero devolviendo el texto segun se genera.

    No cachea: la respuesta se emite trozo a trozo y reconstruirla para
    guardarla obligaria a acumularla entera, perdiendo la ventaja. Las
    preguntas repetidas conviene mandarlas a /chat.
    """
    hits, trozos = await answer_stream(
        db,
        payload.query,
        history=[m.model_dump() for m in payload.history],
    )

    async def eventos() -> AsyncIterator[str]:
        # Las fuentes van primero: el front puede pintar las citas mientras el
        # texto todavia se esta escribiendo.
        yield _sse(
            "sources",
            sources=[
                Source(n=n, source=h.source, page=h.page, similarity=h.similarity).model_dump()
                for n, h in enumerate(hits, start=1)
            ],
        )
        try:
            async for trozo in trozos:
                yield _sse("delta", text=trozo)
        except LLMError as exc:
            # Las cabeceras ya se enviaron, asi que no cabe un 502: el error
            # viaja como un evento mas y lo maneja el cliente.
            yield _sse("error", message=str(exc))
        yield _sse("done")

    return StreamingResponse(
        eventos(),
        media_type="text/event-stream",
        # Sin esto, un proxy intermedio puede bufferizar todo y anular el
        # streaming.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
