"""El contrato HTTP de las tareas."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.models import TaskStatus


class CreateTaskRequest(BaseModel):
    """Lo único que el cliente elige: qué pedir."""

    # Mismo tope que el mensaje de una conversación, y por el mismo motivo: el
    # prompt se persiste y se reenvía en cada vuelta y en cada turno futuro.
    prompt: str = Field(min_length=1, max_length=8_000)


class TaskStepResponse(BaseModel):
    """Un paso, visto desde el progreso.

    Es una proyección más chica que la de la traza de auditoría a propósito:
    "¿cómo va?" se contesta con qué tool está corriendo y si algo falló. Los
    argumentos exactos y la salida completa son otra pregunta —"¿por qué hizo
    eso?"— y viven en `GET /conversations/{id}/log`.
    """

    model_config = ConfigDict(from_attributes=True)

    iteration: int
    tool_name: str
    is_error: bool
    latency_ms: int | None
    created_at: datetime


class PendingApprovalResponse(BaseModel):
    """Una tool sensible esperando decisión.

    Lleva el `tool_input` completo a propósito: quien aprueba tiene que ver
    exactamente qué se va a ejecutar. Un "¿autorizás cancelar un pedido?" sin
    decir cuál no es una aprobación, es un trámite.
    """

    model_config = ConfigDict(from_attributes=True)

    tool_use_id: str
    tool_name: str
    tool_input: dict[str, Any]
    expires_at: datetime


class TaskResponse(BaseModel):
    """El estado de una ejecución.

    Cuando el request devuelva un id en vez de un resultado, este objeto va a ser
    el único canal por donde enterarse de qué pasó — el éxito, el error y la
    pausa se cuentan acá o no se cuentan.
    """

    task_id: str
    conversation_id: str
    status: TaskStatus

    # NULL hasta que termina bien. Trae answer, iterations, tools_used y usage.
    result: dict[str, Any] | None
    # NULL salvo que haya fallado.
    error: str | None

    created_at: datetime
    # created → started es lo que esperó; started → finished es lo que tardó.
    started_at: datetime | None
    finished_at: datetime | None

    # ---- Progreso ----------------------------------------------------------
    #
    # Se calculan de los pasos, no se guardan en la fila. Un contador denormalizado
    # es un contador que algún día va a discrepar de aquello de lo que deriva, y
    # acá derivarlo cuesta una query que ya estamos haciendo.

    # En qué vuelta del loop va. None mientras no ejecutó ninguna tool — que puede
    # significar "todavía no arrancó" o "contestó sin usar tools".
    iteration: int | None = None

    # Lo que hizo hasta ahora. Crece entre un polling y el siguiente porque la
    # traza commitea vuelta a vuelta.
    steps: list[TaskStepResponse] = []

    # Qué está esperando que alguien decida. Vacío salvo en `pending_approval`.
    #
    # Sin este campo, enterarse de qué aprobar requería una consulta SQL: el
    # request que creó la tarea se fue hace rato y el 202 con el pedido de permiso
    # no tiene a quién llegarle. Éste es el canal que lo reemplaza.
    pending_approvals: list[PendingApprovalResponse] = []
