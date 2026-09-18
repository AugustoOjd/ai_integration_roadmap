"""Los endpoints de conversaciones.

    POST /conversations                  abrir la conversación
    GET  /conversations/{id}             ver su estado
    POST /conversations/{id}/messages    un turno

La conversación es un RECURSO, con identidad, estado y ciclo de vida. Es lo que
hace falta para que una conversación pueda quedar pausada esperando una aprobación y
alguien pueda retomarla desde otro request.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.agent.budget import BudgetExceededError
from app.agent.deps import AgentDeps, CurrentUser
from app.agent.loop import run_agent
from app.agent.repository import (
    ConversationPausedError,
    get_conversation,
    load_steps,
    conversation_stats,
)
from app.api.schemas.conversations import (
    ExecutionStepResponse,
    LogResponse,
    MessageRequest,
    PendingApprovalBody,
    ConversationResponse,
    ConversationStats,
    TurnResponse,
    Usage,
)
from app.core.config import settings
from app.core.db import Db
from app.core.models import Conversation, ConversationStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/conversations", tags=["conversations"])


def _a_response(chat: Conversation) -> ConversationResponse:
    """Proyecta el modelo al contrato público.

    `budget_remaining` se calcula, no se guarda: un contador derivado que además
    se persiste es uno que algún día va a discrepar de aquello de lo que deriva.

    Se mide contra el input porque es lo que crece solo — el historial se reenvía
    completo en cada vuelta y en cada turno. El output lo acota max_tokens.
    """
    return ConversationResponse(
        conversation_id=chat.id,
        user_id=chat.user_id,
        status=chat.status,
        budget_tokens=chat.budget_tokens,
        budget_remaining=max(0, chat.budget_tokens - chat.input_tokens_used),
        created_at=chat.created_at,
    )


@router.post(
    "",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Abre una conversación",
)
def crear_conversacion(db: Db, user_id: CurrentUser) -> ConversationResponse:
    """Crea la conversación vacía. No llama al modelo ni cuesta un token.

    Sin body: el dueño sale de CurrentUser, o sea del canal autenticado. Con el
    user_id en el JSON, abrir una conversación a nombre de otro sería cuestión de
    cambiar una línea del curl.

    El presupuesto se COPIA del default de config a la fila: si mañana bajás el
    default, las conversaciones abiertas siguen con las reglas con las que empezaron.
    """
    chat = Conversation(
        user_id=user_id,
        budget_tokens=settings.DEFAULT_BUDGET_TOKENS,
    )
    db.add(chat)
    # El commit es de la ruta y no de la dependencia: acá la unidad de trabajo es
    # obvia y chiquita. En save_turn no lo es, y por eso aquella función se
    # encarga sola.
    db.commit()

    logger.info("conversación creada id=%s user=%s", chat.id, chat.user_id)
    return _a_response(chat)


@router.get(
    "/{conversation_id}",
    response_model=ConversationResponse,
    summary="Estado de una conversación",
)
def ver_conversacion(conversation_id: str, db: Db, user_id: CurrentUser) -> ConversationResponse:
    """Si no existe —o no es tuya—, get_conversation levanta y errors.py hace el 404."""
    return _a_response(get_conversation(db, conversation_id, user_id=user_id))


@router.get(
    "/{conversation_id}/log",
    response_model=LogResponse,
    summary="La traza de ejecución de una conversación",
)
def ver_log(
    conversation_id: str,
    db: Db,
    user_id: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    before_id: Annotated[
        int | None, Query(description="Cursor: id del último paso visto")
    ] = None,
) -> LogResponse:
    """Contesta "¿por qué el agente hizo eso?" tres días después y sin grep.

    Va con el mismo CurrentUser que el resto: la traza de una conversación es tan
    privada como la conversación. De hecho más, porque contiene los argumentos
    exactos con los que se llamó a cada tool.
    """
    # El chequeo de dueño primero: si la conversación no es tuya, ni siquiera llegamos a
    # consultar la traza.
    get_conversation(db, conversation_id, user_id=user_id)

    pasos = load_steps(db, conversation_id, limit=limit, before_id=before_id)

    # Si vino una página completa asumimos que puede haber más; si vino incompleta,
    # seguro que no. El caso borde —que la última página tenga exactamente `limit`
    # elementos— hace que el cliente pida una página más y reciba una vacía, que es
    # preferible a pedir limit+1 filas en cada consulta para saberlo con certeza.
    siguiente = pasos[-1].id if len(pasos) == limit else None

    return LogResponse(
        steps=[ExecutionStepResponse.model_validate(paso) for paso in pasos],
        next_before_id=siguiente,
        stats=ConversationStats(**conversation_stats(db, conversation_id)),
    )


@router.post(
    "/{conversation_id}/messages",
    response_model=TurnResponse,
    summary="Manda un mensaje y corre el agente",
    # El 202 no sale de esta función: lo arma el handler de ApprovalRequired en
    # errors.py. Se declara acá para que aparezca en OpenAPI — si no, un cliente
    # que lee el schema no se entera de que este endpoint puede no devolverle una
    # respuesta.
    responses={
        202: {"model": PendingApprovalBody, "description": "Una tool sensible espera aprobación"},
        409: {"description": "La conversación ya está esperando una aprobación"},
    },
)
def mandar_mensaje(
    conversation_id: str, request: MessageRequest, db: Db, user_id: CurrentUser
) -> TurnResponse:
    """Un turno completo: carga el historial, corre el loop, guarda.

    Acá no hay ningún `try`: todo lo que puede fallar tiene su handler registrado
    en errors.py, así que la ruta se lee como el camino feliz.

    Sí hay una verificación explícita: la conversación se busca ANTES de correr el
    agente. Dejar que save_turn descubra al final que no existe significaría haber
    gastado varias llamadas al modelo en una conversación imaginaria.
    """
    chat = get_conversation(db, conversation_id, user_id=user_id)

    # Una conversación pausada no acepta mensajes nuevos. Si los aceptara, el turno nuevo
    # arrancaría sobre un historial con un tool_use sin cerrar —y la API lo
    # rechazaría con un 400— o peor, quedarían dos corridas entrelazadas.
    if chat.status is ConversationStatus.PENDING_APPROVAL:
        raise ConversationPausedError(chat.id)

    # Una conversación agotada se corta acá, sin llegar a count_tokens ni a nada: es el
    # chequeo más barato posible para el caso más común de rechazo.
    if chat.status is ConversationStatus.EXHAUSTED:
        raise BudgetExceededError(
            necesarios=0,
            disponibles=max(0, chat.budget_tokens - chat.input_tokens_used),
        )

    # Acá se arma el contexto que las tools van a recibir, con el user_id
    # VERIFICADO y no el que pudiera aparecer en request.prompt. Éste es el único
    # lugar del sistema donde el dueño de la corrida se decide, y que sea uno solo
    # es lo que hace auditable la regla entera.
    deps = AgentDeps(user_id=chat.user_id, conversation_id=chat.id, db=db)

    result = run_agent(db, chat.id, request.prompt, deps)

    # `chat` ya refleja los tokens del turno sin volver a consultar: save_turn pidió
    # la misma sesión de SQLAlchemy y el mapa de identidad devolvió este mismo
    # objeto. Y sigue legible después del commit gracias a expire_on_commit=False.
    logger.info(
        "turno ok conversation=%s iterations=%d tools=%s in=%d out=%d",
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
