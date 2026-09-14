"""El endpoint de decisión (Fase 6).

    POST /sessions/{session_id}/approvals/{tool_use_id}
    {"approved": true}

Un endpoint chiquito con una responsabilidad grande: es el punto donde una
persona autoriza que un modelo de lenguaje ejecute algo irreversible.

Fijate que la decisión es un POST sobre un sub-recurso y no un `PATCH` de la
sesión. La aprobación es una cosa con identidad propia —tiene su `tool_use_id`,
su vencimiento y su estado— y tratarla como tal es lo que hace que el candado de
idempotencia tenga dónde vivir.
"""

import logging

from fastapi import APIRouter

from app.agent import resume_run
from app.db import Db
from app.deps import AgentDeps, CurrentUser
from app.repository import get_session
from app.schemas.sessions import (
    ApprovalDecision,
    PendingApprovalBody,
    TurnResponse,
    Usage,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions", tags=["approvals"])


@router.post(
    "/{session_id}/approvals/{tool_use_id}",
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
async def decidir(
    session_id: str,
    tool_use_id: str,
    decision: ApprovalDecision,
    db: Db,
    user_id: CurrentUser,
) -> TurnResponse:
    """Registra la decisión y devuelve la respuesta final del agente.

    Es **sincrónico**: cuando aprobás, este request corre la tool y después
    sigue el loop hasta que el modelo termine. Por eso devuelve un `TurnResponse`
    completo y no un simple "ok".

    La alternativa sería contestar 204 y que el cliente vuelva a preguntar. Sería
    más prolijo para la latencia y peor para quien usa esto: el usuario que
    acaba de autorizar algo quiere ver qué pasó, no recibir un acuse de recibo.

    Todos los errores —no existe, ya se decidió, venció, no es tuya— los traduce
    `errors.py`. Acá no hay un solo `try`.
    """
    chat = await get_session(db, session_id, user_id=user_id)

    deps = AgentDeps(user_id=chat.user_id, session_id=chat.id, db=db)

    logger.info(
        "decisión session=%s tool_use=%s aprobada=%s", chat.id, tool_use_id, decision.approved
    )

    result = await resume_run(
        db, chat.id, tool_use_id, approved=decision.approved, deps=deps
    )

    return TurnResponse(
        answer=result.text,
        iterations=result.iterations,
        tools_used=result.tools_used,
        usage=Usage(input_tokens=result.input_tokens, output_tokens=result.output_tokens),
        budget_remaining=max(0, chat.budget_tokens - chat.input_tokens_used),
    )
