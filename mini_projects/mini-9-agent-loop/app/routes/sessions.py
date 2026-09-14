"""Los endpoints de sesiones.

El mini 8 tenía un endpoint sin estado: `POST /agent/tool-calling`, mandás un
prompt, te llevás una respuesta, se acabó. Acá la conversación es un RECURSO, y
eso cambia la forma de la API:

    POST /sessions                  abrir la conversación
    GET  /sessions/{id}             ver su estado
    POST /sessions/{id}/messages    un turno

No es cosmética. Un recurso tiene identidad, estado y ciclo de vida — y es
justamente lo que hace falta para que en la Fase 5 una sesión pueda quedar
PAUSADA esperando una aprobación, y en la Fase 6 alguien pueda retomarla desde
otro request.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.agent import run_agent
from app.budget import BudgetExceededError
from app.config import settings
from app.db import Db
from app.deps import AgentDeps, CurrentUser
from app.models import ChatSession, SessionStatus
from app.repository import (
    SessionPausedError,
    get_session,
    load_steps,
    session_stats,
)
from app.schemas.sessions import (
    ExecutionStepResponse,
    LogResponse,
    MessageRequest,
    PendingApprovalBody,
    SessionResponse,
    SessionStats,
    TurnResponse,
    Usage,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _a_response(chat: ChatSession) -> SessionResponse:
    """Proyecta el modelo al contrato público.

    `budget_remaining` se CALCULA, no se guarda. Un contador derivado que además
    se persiste es un contador que algún día va a discrepar de aquello de lo que
    deriva; guardar sólo lo consumido y restar al leer no puede desincronizarse.

    Se mide contra el input porque es lo que crece solo: el historial se reenvía
    completo en cada vuelta y en cada turno. El output lo acota `max_tokens` y
    no se dispara así.
    """
    return SessionResponse(
        session_id=chat.id,
        user_id=chat.user_id,
        status=chat.status,
        budget_tokens=chat.budget_tokens,
        budget_remaining=max(0, chat.budget_tokens - chat.input_tokens_used),
        created_at=chat.created_at,
    )


@router.post(
    "",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Abre una conversación",
)
async def crear_sesion(db: Db, user_id: CurrentUser) -> SessionResponse:
    """Crea la sesión vacía. No llama al modelo ni cuesta un token.

    Sin body: el dueño sale de `CurrentUser`, o sea del canal autenticado. Antes
    de la Fase 3 venía en el JSON, y eso significaba que abrir una conversación
    a nombre de otro era cuestión de cambiar una línea del curl.

    El presupuesto se COPIA del default de config a la fila, en vez de leerse de
    config cada vez que se chequea. Si mañana bajás el default, las sesiones ya
    abiertas siguen con las reglas con las que empezaron — cambiarle las reglas
    a una conversación en curso es la clase de sorpresa que nadie puede
    debuggear desde afuera.
    """
    chat = ChatSession(
        user_id=user_id,
        budget_tokens=settings.DEFAULT_BUDGET_TOKENS,
    )
    db.add(chat)
    # El commit es de la ruta, no de la dependencia: acá la unidad de trabajo es
    # obvia y chiquita (una fila). En `save_turn` no lo es, y por eso aquella
    # función se encarga sola. Ver la nota en `db.get_db`.
    await db.commit()

    logger.info("sesión creada id=%s user=%s", chat.id, chat.user_id)
    return _a_response(chat)


@router.get("/{session_id}", response_model=SessionResponse, summary="Estado de una sesión")
async def ver_sesion(session_id: str, db: Db, user_id: CurrentUser) -> SessionResponse:
    """Si no existe —o no es tuya—, `get_session` levanta y `errors.py` hace el 404."""
    return _a_response(await get_session(db, session_id, user_id=user_id))


@router.get(
    "/{session_id}/log",
    response_model=LogResponse,
    summary="La traza de ejecución de una sesión",
)
async def ver_log(
    session_id: str,
    db: Db,
    user_id: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    before_id: Annotated[int | None, Query(description="Cursor: id del último paso visto")] = None,
) -> LogResponse:
    """La pregunta que este endpoint contesta es "¿por qué el agente hizo eso?".

    Tres días después, para una sesión concreta, sin grep. Ésa es la razón por
    la que la traza es una tabla y no un `print`: un agente que toca datos de un
    usuario y ejecuta acciones a su nombre necesita poder explicarse.

    Va con el mismo `CurrentUser` que el resto: la traza de una conversación es
    tan privada como la conversación. De hecho más — contiene los argumentos
    exactos con los que se llamó a cada tool.
    """
    # El chequeo de dueño primero. Si la sesión no es tuya, ni siquiera llegamos
    # a consultar la traza.
    await get_session(db, session_id, user_id=user_id)

    pasos = await load_steps(db, session_id, limit=limit, before_id=before_id)

    # El cursor de la página siguiente. Si vino una página completa asumimos que
    # puede haber más; si vino incompleta, seguro que no.
    #
    # El caso borde —que la última página tenga exactamente `limit` elementos—
    # hace que el cliente pida una página más y reciba una vacía. Es preferible
    # a la alternativa, que sería pedir `limit + 1` filas en cada consulta para
    # saberlo con certeza.
    siguiente = pasos[-1].id if len(pasos) == limit else None

    return LogResponse(
        steps=[ExecutionStepResponse.model_validate(paso) for paso in pasos],
        next_before_id=siguiente,
        stats=SessionStats(**await session_stats(db, session_id)),
    )


@router.post(
    "/{session_id}/messages",
    response_model=TurnResponse,
    summary="Manda un mensaje y corre el agente",
    # El 202 no sale de esta función: lo arma el handler de `ApprovalRequired`
    # en `errors.py`. Se declara acá para que aparezca en la documentación de
    # OpenAPI — si no, un cliente que lee el schema no se entera de que este
    # endpoint puede no devolverle una respuesta.
    responses={
        202: {"model": PendingApprovalBody, "description": "Una tool sensible espera aprobación"},
        409: {"description": "La sesión ya está esperando una aprobación"},
    },
)
async def mandar_mensaje(
    session_id: str, request: MessageRequest, db: Db, user_id: CurrentUser
) -> TurnResponse:
    """Un turno completo: carga el historial, corre el loop, guarda.

    Fijate que acá no hay ningún `try`. Todo lo que puede fallar —la sesión que
    no existe, el agente que no converge, el rate limit del proveedor— tiene su
    handler registrado en `errors.py`. La ruta se lee como el camino feliz
    porque es lo único que le toca decidir.

    Sí hay una verificación explícita: la sesión se busca ANTES de correr el
    agente. Podríamos dejar que `save_turn` descubra al final que no existe,
    pero para entonces ya gastaste varias llamadas al modelo en una conversación
    imaginaria. El chequeo barato va primero.
    """
    chat = await get_session(db, session_id, user_id=user_id)

    # ------------------------------------------------------------- Fase 5
    # Una sesión pausada no acepta mensajes nuevos. Si los aceptara, el turno
    # nuevo arrancaría sobre un historial que tiene un `tool_use` sin cerrar —y
    # la API lo rechazaría con un 400— o peor, quedarían dos corridas
    # entrelazadas sin ningún orden que tenga sentido.
    if chat.status is SessionStatus.PENDING_APPROVAL:
        raise SessionPausedError(chat.id)

    # ------------------------------------------------------------- Fase 7
    # Una sesión agotada se corta acá, sin llegar a `count_tokens` ni a nada.
    # Es el chequeo más barato posible para el caso más común de rechazo: la
    # sesión ya se pasó, y todo request siguiente va a dar lo mismo.
    if chat.status is SessionStatus.EXHAUSTED:
        raise BudgetExceededError(
            necesarios=0,
            disponibles=max(0, chat.budget_tokens - chat.input_tokens_used),
        )

    # ------------------------------------------------------------- Fase 3
    # Acá se arma el contexto que las tools van a recibir, y el `user_id` que va
    # adentro es el VERIFICADO, no el que pudiera aparecer en `request.prompt`.
    #
    # Éste es el único lugar del sistema donde el dueño de la corrida se decide.
    # Que sea uno solo es lo que hace auditable la regla entera: no hay que
    # revisar tool por tool si alguna se lo cree al modelo.
    deps = AgentDeps(user_id=chat.user_id, session_id=chat.id, db=db)

    result = await run_agent(db, chat.id, request.prompt, deps)

    # `chat` ya refleja los tokens del turno sin volver a consultar: `save_turn`
    # pidió la MISMA sesión de SQLAlchemy y el mapa de identidad devolvió este
    # mismo objeto Python. Y sigue siendo legible después del commit gracias a
    # `expire_on_commit=False` (ver `db.py`).
    logger.info(
        "turno ok session=%s iterations=%d tools=%s in=%d out=%d",
        chat.id,
        result.iterations,
        result.tools_used,
        result.input_tokens,
        result.output_tokens,
    )

    return TurnResponse(
        answer=result.text,
        iterations=result.iterations,
        tools_used=result.tools_used,
        usage=Usage(input_tokens=result.input_tokens, output_tokens=result.output_tokens),
        budget_remaining=max(0, chat.budget_tokens - chat.input_tokens_used),
    )
