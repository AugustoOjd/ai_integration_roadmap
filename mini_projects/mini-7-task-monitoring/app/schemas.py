from typing import Any

from pydantic import BaseModel, Field


class FlakyRequest(BaseModel):
    # Con fail_times > max_retries (3) la tarea agota los reintentos y termina
    # en FAILURE. Acotamos en 10 para que el ejemplo no se vuelva eterno: cada
    # reintento espera, y el backoff crece.
    fail_times: int = Field(ge=0, le=10)


class FetchRequest(BaseModel):
    resource_id: str = Field(min_length=1, max_length=64)
    # El status que va a "devolver" el servicio externo simulado. 200 = éxito,
    # 503 = transitorio (reintenta), 404 = permanente (muere en el primer
    # intento). Es el parámetro que nos deja recorrer las tres ramas a mano.
    #
    # Acotado al rango real de HTTP: un 999 no lo produce ningún servidor y no
    # tiene sentido dejar que llegue al worker.
    simulated_status: int = Field(default=200, ge=100, le=599)


class EnqueueResponse(BaseModel):
    task_id: str
    status: str


class DeadLetterEntry(BaseModel):
    """Una tarea muerta. El schema documenta qué se puede esperar de la DLQ."""

    task_id: str
    task_name: str
    args: list[Any]
    kwargs: dict[str, Any]
    exc_type: str
    exc_message: str
    # 0 = murió en el primer intento (error permanente).
    # >0 = agotó el presupuesto de reintentos (error transitorio prolongado).
    retries: int
    failed_at: str


class DeadLetterPage(BaseModel):
    # `total` es el tamaño de la DLQ completa; `entries` es solo la página que
    # se pidió. Sin el total, el cliente no puede saber si hay 3 fallos o 3000.
    total: int
    entries: list[DeadLetterEntry]


class ReplayResponse(BaseModel):
    reenviadas: int


class ClearResponse(BaseModel):
    # Schema propio en vez de reusar ReplayResponse: son dos operaciones con
    # consecuencias opuestas —una recupera trabajo, la otra lo tira— y el nombre
    # del campo es lo que se lo dice al que lee la respuesta.
    descartadas: int


class StatusResponse(BaseModel):
    task_id: str
    status: str
    # ready = terminó, con éxito o con error. Se expone aparte del status para
    # que el cliente no tenga que conocer el vocabulario de estados de Celery
    # ni saber cuáles cuentan como terminales.
    ready: bool
    # En RETRY y en FAILURE el backend no guarda un resultado sino la excepción.
    # La devolvemos como texto: el cliente no puede reconstruir la clase, y
    # además el mensaje es lo único que le sirve.
    detail: str | None = None
    # El valor de retorno, solo cuando la tarea salió bien.
    result: dict[str, Any] | None = None
