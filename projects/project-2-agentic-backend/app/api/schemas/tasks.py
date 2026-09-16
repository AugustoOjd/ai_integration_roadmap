"""El contrato HTTP de las tareas."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.core.models import TaskStatus


class CreateTaskRequest(BaseModel):
    """Lo único que el cliente elige: qué pedir."""

    # Mismo tope que el mensaje de una conversación, y por el mismo motivo: el
    # prompt se persiste y se reenvía en cada vuelta y en cada turno futuro.
    prompt: str = Field(min_length=1, max_length=8_000)


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
