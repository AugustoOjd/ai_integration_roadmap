"""El contrato HTTP de las sesiones.

Los schemas son la frontera entre lo que el mundo puede mandarte y lo que tu
código asume. Todo lo que cruza esta capa está validado; nada de lo que sale
expone estado interno que no elegiste exponer.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models import SessionStatus


# NOTA (Fase 3): acá vivía un `CreateSessionRequest` con un `user_id` en el body.
# Ya no existe, y su ausencia es el cambio.
#
# Un identificador de usuario que el cliente elige es uno que el cliente puede
# falsificar: `{"user_id": "u_7"}` y listo. Ahora `POST /sessions` no lleva body
# — el dueño sale del contexto autenticado, que el cliente no elige.
#
# Es la misma regla que la de las tools, un nivel más arriba: lo que define
# permisos no viaja por un canal que la otra punta controla.


class SessionResponse(BaseModel):
    """El estado de una conversación."""

    # Deja que Pydantic lea atributos de un objeto del ORM además de dicts.
    # Es lo que permite `SessionResponse.model_validate(chat)` sin armar el dict
    # a mano — y, más importante, hace explícito que la respuesta es una
    # PROYECCIÓN del modelo, no el modelo: `input_tokens_used` existe en la
    # tabla y no aparece acá porque nadie afuera necesita ese detalle.
    model_config = ConfigDict(from_attributes=True)

    session_id: str
    user_id: str
    status: SessionStatus
    budget_tokens: int
    budget_remaining: int
    created_at: datetime


class MessageRequest(BaseModel):
    """Un turno de conversación."""

    # El `max_length` no es burocracia: sin tope, un prompt de 500 KB entra al
    # historial, se persiste, y se REENVÍA en cada vuelta del loop y en cada
    # turno futuro de la sesión. Un solo request mal intencionado te encarece la
    # conversación entera para siempre.
    prompt: str = Field(min_length=1, max_length=8_000)


class Usage(BaseModel):
    """Lo que costó el turno. Sumado sobre todas las vueltas del loop."""

    input_tokens: int
    output_tokens: int


# ---------------------------------------------------------------------------
# Aprobaciones (Fase 5)
# ---------------------------------------------------------------------------


class PendingApprovalResponse(BaseModel):
    """Una tool sensible esperando decisión.

    Lleva el `tool_input` completo a propósito: quien aprueba tiene que poder
    ver EXACTAMENTE qué se va a ejecutar. Un "¿autorizás cancelar un pedido?"
    sin decir cuál no es una aprobación, es un trámite.
    """

    model_config = ConfigDict(from_attributes=True)

    # El id del bloque `tool_use`. Es lo que se manda de vuelta para decidir.
    tool_use_id: str
    tool_name: str
    tool_input: dict[str, Any]
    expires_at: datetime


class ApprovalDecision(BaseModel):
    """El sí o el no.

    Un booleano y nada más: ni el `tool_input` ni el nombre de la tool viajan de
    vuelta. Los argumentos que se van a ejecutar son los que quedaron
    persistidos en el 202 — si el cliente pudiera mandarlos de nuevo, podría
    mandar OTROS, y "aprobar" pasaría a ser "ejecutar lo que yo diga". El
    permiso es sobre una acción concreta, no sobre una tool en abstracto.
    """

    approved: bool


class PendingApprovalBody(BaseModel):
    """El cuerpo del 202. No es la respuesta del agente: es un pedido de permiso."""

    status: str = "pending_approval"
    session_id: str
    pending: list[PendingApprovalResponse]


# ---------------------------------------------------------------------------
# La traza (Fase 4)
# ---------------------------------------------------------------------------


class ExecutionStepResponse(BaseModel):
    """Un paso de la traza, como se lo devolvemos a quien audita."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    turn: int
    iteration: int
    tool_name: str
    tool_input: dict[str, Any]
    tool_output: str | None
    is_error: bool
    latency_ms: int | None
    # En NULL salvo en el primer paso de cada vuelta: los tokens son de la
    # llamada al modelo, no de cada tool. Ver el comentario en `agent.py`.
    input_tokens: int | None
    output_tokens: int | None
    created_at: datetime


class SessionStats(BaseModel):
    """El resumen de una sesión: lo que mirás antes de leer paso por paso."""

    total_steps: int
    failed_steps: int
    # Cuántas veces se llamó a cada tool, de la más usada a la menos.
    tools: dict[str, int]
    input_tokens: int
    output_tokens: int


class LogResponse(BaseModel):
    """La traza paginada.

    `next_before_id` es el cursor para pedir la página siguiente, y es `None`
    cuando no hay más. Se devuelve explícito en vez de hacer que el cliente lo
    deduzca del último elemento: si mañana cambia el criterio de paginación, el
    cliente no se entera.
    """

    steps: list[ExecutionStepResponse]
    next_before_id: int | None
    stats: SessionStats


class TurnResponse(BaseModel):
    """La respuesta del agente, más su traza.

    `answer` es lo único que le interesa al usuario final. Todo el resto está
    para VOS: sin `iterations`, `tools_used` y `usage`, un agente en producción
    es una caja negra que no podés ni debuggear ni costear.
    """

    answer: str
    iterations: int
    # Con repetidos y en orden de invocación: si el modelo llamó `calculate`
    # tres veces, querés verlo tres veces. Un `set` escondería justo el síntoma
    # que estás buscando.
    tools_used: list[str]
    usage: Usage
    budget_remaining: int
