from typing import Any

from pydantic import BaseModel, Field


class EnqueueRequest(BaseModel):
    # ge/le acotan la entrada antes de encolar: una tarea inválida no debería
    # llegar a gastar un slot del worker.
    value: int = Field(ge=0, le=1_000_000)


class FlakyRequest(BaseModel):
    # Con fail_times > max_retries (3) la tarea agota los reintentos y termina
    # en FAILURE: sirve para ver los dos desenlaces.
    fail_times: int = Field(ge=0, le=10)


class EnqueueResponse(BaseModel):
    task_id: str
    status: str


class StatusResponse(BaseModel):
    task_id: str
    status: str
    # ready = terminó (con éxito o error). Lo exponemos aparte del status para
    # que el cliente no tenga que conocer el vocabulario de estados de Celery.
    ready: bool


class ResultResponse(BaseModel):
    task_id: str
    status: str
    # None mientras no haya terminado; el endpoint devuelve 202 en ese caso.
    result: dict[str, Any] | None = None
