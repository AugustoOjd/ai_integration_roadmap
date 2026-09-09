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


class BatchRequest(BaseModel):
    # Cada ítem tarda 1 segundo. El techo de 120 es para que el ejemplo siga
    # siendo un ejemplo y no choque con el task_time_limit de 360s.
    total_items: int = Field(ge=1, le=120)


class ProgressResponse(BaseModel):
    task_id: str
    status: str
    # None cuando el progreso es DESCONOCIDO, que no es lo mismo que 0. Una
    # tarea en PENDING puede estar en cola o no existir: afirmar "0%" sería
    # inventar información. El cliente muestra una barra indeterminada.
    percent: int | None = None
    current: int | None = None
    total: int | None = None
    detail: str | None = None
    result: dict[str, Any] | None = None


class RevokeResponse(BaseModel):
    task_id: str
    # "solicitada", no "aplicada". revoke() no confirma nada: publica la orden
    # y vuelve. Un campo llamado `revoked: true` sería mentira.
    requested: bool
    terminate: bool
    # El estado leído JUSTO DESPUÉS de mandar la orden. Puede seguir siendo
    # PENDING o STARTED porque la revocación viaja de forma asíncrona; el
    # cliente tiene que volver a consultar para ver REVOKED.
    status: str


class EnqueueResponse(BaseModel):
    task_id: str
    status: str


class ActiveTask(BaseModel):
    """Una tarea corriendo ahora mismo.

    Celery devuelve esto anidado por worker; nosotros lo aplanamos y le metemos
    el nombre del worker adentro. Una lista plana es más fácil de ordenar,
    filtrar y paginar que un dict de listas, y el cliente no pierde nada.
    """

    worker: str
    task_id: str
    name: str
    # `Any` a propósito: Celery cambió el formato de estos campos entre
    # versiones (a veces lista, a veces el repr como string). Fijar un tipo
    # estricto acá haría que una actualización de Celery rompa el endpoint.
    # Que el formato de ellos sea inestable es justo la razón de tener schema
    # propio: lo aislamos en un campo en vez de exponerlo en toda la respuesta.
    args: Any = None
    kwargs: Any = None
    # Epoch en segundos, del reloj del WORKER. Con varios workers en máquinas
    # distintas los relojes no coinciden exactamente: sirve para ordenar y
    # estimar duración, no como timestamp legal.
    started_at: float | None = None


class ScheduledTask(BaseModel):
    """Una tarea esperando su hora: reintentos con countdown y ETAs.

    Es la vista donde se ve el backoff de la Fase 1 en vivo.
    """

    worker: str
    task_id: str
    name: str
    # Momento exacto del próximo intento, en ISO 8601. La diferencia contra
    # `now` es lo que falta de backoff.
    eta: str | None = None


class WorkerSummary(BaseModel):
    """Estado de un worker. Un subconjunto elegido de lo que da `stats()`.

    `stats()` devuelve decenas de claves (rusage, pid del pool, broker, clock).
    Exponer todo eso sería filtrar la estructura interna de Celery a nuestros
    clientes y quedar atados a ella.
    """

    name: str
    # Cuántas tareas puede ejecutar en paralelo (el -c del comando).
    concurrency: int | None = None
    pool: str | None = None
    # Segundos desde que arrancó el proceso.
    uptime: int | None = None
    # Acumulado POR PROCESO: {"tasks.flaky": 12, ...}. Se resetea al reiniciar
    # el worker, así que es una foto, no una métrica histórica.
    total: dict[str, int] = Field(default_factory=dict)


class WorkersResponse(BaseModel):
    # healthy=False significa "ningún worker contestó el broadcast". Va como
    # campo y no como código de error: este endpoint tiene que responder 200
    # justamente cuando el cluster está caído.
    healthy: bool
    workers: list[WorkerSummary] = Field(default_factory=list)


class ActiveTasksResponse(BaseModel):
    healthy: bool
    count: int
    tasks: list[ActiveTask] = Field(default_factory=list)


class ScheduledTasksResponse(BaseModel):
    healthy: bool
    count: int
    tasks: list[ScheduledTask] = Field(default_factory=list)


class DashboardResponse(BaseModel):
    """Los números de una sola pantalla, sin el detalle de cada tarea."""

    healthy: bool
    workers_online: int
    active: int
    # Prefetcheadas: sacadas de la cola pero todavía sin empezar.
    reserved: int
    # Esperando su hora, incluidos los reintentos pendientes.
    scheduled: int
    # Fallos definitivos acumulados. Un número que sube solo es la señal más
    # barata de que algo se rompió.
    dead_letter: int


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
