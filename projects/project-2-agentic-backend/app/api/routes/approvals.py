"""El endpoint de decisión.

    POST /conversations/{conversation_id}/approvals/{tool_use_id}
    {"approved": true}

Un endpoint chiquito con una responsabilidad grande: es el punto donde una
persona autoriza que un modelo de lenguaje ejecute algo irreversible.

La decisión es un POST sobre un sub-recurso y no un PATCH de la conversación. La
aprobación tiene identidad propia —su tool_use_id, su vencimiento y su estado— y
tratarla como tal es lo que hace que el candado de idempotencia tenga dónde
vivir.
"""

import logging

from fastapi import APIRouter

from app.agent.deps import AgentDeps, CurrentUser
from app.agent.loop import ApprovalRequired, resume_run
from app.agent.repository import decidir_aprobacion, get_conversation, pendientes_de
from app.api.schemas.conversations import (
    ApprovalDecision,
    PendingApprovalBody,
    TurnResponse,
    Usage,
)
from app.core.db import Db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/conversations", tags=["approvals"])


@router.post(
    "/{conversation_id}/approvals/{tool_use_id}",
    response_model=TurnResponse,
    summary="Aprueba o rechaza una tool sensible y retoma la corrida",
    responses={
        202: {
            "model": PendingApprovalBody,
            "description": "Quedan otras tools sensibles por decidir en el mismo turno",
        },
        409: {"description": "Ya se decidió, o el pedido venció"},
    },
)
def decidir(
    conversation_id: str,
    tool_use_id: str,
    decision: ApprovalDecision,
    db: Db,
    user_id: CurrentUser,
) -> TurnResponse:
    """Registra la decisión y devuelve la respuesta final del agente.

    Cuando aprobás, este request corre la tool y después sigue el loop hasta que el
    modelo termine. Por eso devuelve un TurnResponse completo y no un "ok".

    La alternativa sería contestar 204 y que el cliente vuelva a preguntar: mejor
    para la latencia y peor para quien usa esto, porque el usuario que acaba de
    autorizar algo quiere ver qué pasó, no un acuse de recibo.

    Todos los errores —no existe, ya se decidió, venció, no es tuya— los traduce
    errors.py. Acá no hay un solo `try`.
    """
    chat = get_conversation(db, conversation_id, user_id=user_id)

    deps = AgentDeps(user_id=chat.user_id, conversation_id=chat.id, db=db)

    logger.info(
        "decisión conversation=%s tool_use=%s aprobada=%s",
        chat.id,
        tool_use_id,
        decision.approved,
    )

    # Decidir y retomar están separados desde que la retoma puede correr en un
    # worker. Acá pasan seguidos, en el mismo request, pero el orden es el mismo:
    # la decisión se persiste antes de ejecutar nada.
    decidir_aprobacion(db, chat.id, tool_use_id, approved=decision.approved)

    # ¿Queda otra tool sensible del mismo turno? Los tool_result van todos en un
    # mensaje, así que no se puede retomar hasta que estén todas resueltas.
    restantes = [p for p in pendientes_de(db, chat.id) if p.tool_use_id != tool_use_id]
    if restantes:
        raise ApprovalRequired(chat.id, restantes)

    result = resume_run(db, chat.id, tool_use_id, deps=deps)

    return TurnResponse(
        answer=result.text,
        iterations=result.iterations,
        tools_used=result.tools_used,
        usage=Usage(input_tokens=result.input_tokens, output_tokens=result.output_tokens),
        budget_remaining=max(0, chat.budget_tokens - chat.input_tokens_used),
    )
