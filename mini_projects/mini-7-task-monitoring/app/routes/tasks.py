from celery.result import AsyncResult
from fastapi import APIRouter, Query, status

from app.celery_app import celery_app
from app.schemas import (
    BatchRequest,
    EnqueueResponse,
    FetchRequest,
    FlakyRequest,
    ProgressResponse,
    RevokeResponse,
    StatusResponse,
)
from app.services import task_control
from app.tasks import fetch_resource, flaky, process_batch

router = APIRouter(prefix="/tasks", tags=["tasks"])


# Endpoints SIN async: todo lo de acá abajo habla con Redis por un socket
# bloqueante (.delay(), AsyncResult). Declarados sync, FastAPI los corre en su
# threadpool y no bloquean el event loop; con `async def` sí lo bloquearían.
@router.post("/flaky", response_model=EnqueueResponse, status_code=status.HTTP_202_ACCEPTED)
def enqueue_flaky(payload: FlakyRequest) -> EnqueueResponse:
    """Encola la tarea intermitente y responde de inmediato.

    202 y no 201: "aceptado, todavía no procesado". Es el código honesto para
    una API que delega el trabajo — cuando respondemos, la tarea puede no haber
    empezado siquiera.
    """
    # .delay() serializa los args a JSON, hace LPUSH en la cola y devuelve un
    # AsyncResult sin esperar al worker.
    async_result = flaky.delay(payload.fail_times)
    return EnqueueResponse(task_id=async_result.id, status=async_result.state)


@router.post("/fetch", response_model=EnqueueResponse, status_code=status.HTTP_202_ACCEPTED)
def enqueue_fetch(payload: FetchRequest) -> EnqueueResponse:
    """Encola una llamada a un servicio externo simulado.

    Según el `simulated_status` la tarea toma una de tres rutas distintas, y esa
    diferencia es todo el punto de la fase:

      200 → SUCCESS en el primer intento
      503 → TransientError → 3 reintentos con backoff → SUCCESS o FAILURE
      404 → PermanentError → FAILURE inmediato, sin un solo reintento
    """
    async_result = fetch_resource.delay(payload.resource_id, payload.simulated_status)
    return EnqueueResponse(task_id=async_result.id, status=async_result.state)


@router.post("/batch", response_model=EnqueueResponse, status_code=status.HTTP_202_ACCEPTED)
def enqueue_batch(payload: BatchRequest) -> EnqueueResponse:
    """Encola una tarea larga que reporta su avance."""
    async_result = process_batch.delay(payload.total_items)
    return EnqueueResponse(task_id=async_result.id, status=async_result.state)


@router.get("/{task_id}/progress", response_model=ProgressResponse)
def get_task_progress(task_id: str) -> ProgressResponse:
    """Avance de una tarea larga, en un formato que un cliente pueda dibujar.

    Todo el trabajo de este endpoint es traducir. En el backend, `info` guarda
    cosas de NATURALEZA distinta según el estado —un dict de progreso, un valor
    de retorno, una excepción— y leerlo sin mirar antes el estado es la forma
    segura de romperse. Esa traducción va acá y no en el cliente.
    """
    async_result = AsyncResult(task_id, app=celery_app)
    state = async_result.state
    response = ProgressResponse(task_id=task_id, status=state)

    if state == "PROGRESS":
        # info es el dict que mandamos en update_state(meta=...). Usamos .get()
        # y no acceso directo: si una versión vieja de la tarea reportó otro
        # formato, el endpoint degrada en vez de tirar un KeyError.
        meta = async_result.info or {}
        current = meta.get("current")
        total = meta.get("total")

        response.current = current
        response.total = total
        # El guard de total: una división por cero acá dejaría sin monitoreo
        # justo a la tarea que se está monitoreando.
        if current is not None and total:
            response.percent = int(current * 100 / total)

    elif state == "SUCCESS":
        # 100 explícito: la tarea terminada nunca reporta su último tramo,
        # porque el return pisa el meta de progreso.
        response.percent = 100
        response.result = async_result.result

    elif state in ("RETRY", "FAILURE"):
        # Acá info es la EXCEPCIÓN, no un dict. De ahí que no se pueda leer
        # `info["current"]` sin preguntar antes por el estado.
        response.detail = str(async_result.info)

    # PENDING y STARTED caen acá sin tocar nada: percent queda en None, que
    # significa "no sé", no "0%".
    return response


@router.get("/{task_id}/status", response_model=StatusResponse)
def get_task_status(task_id: str) -> StatusResponse:
    """Estado actual de una tarea. Nunca bloquea esperando a que termine."""
    # AsyncResult solo LEE el backend; no reencola ni valida nada. Un task_id
    # inventado devuelve PENDING, porque en Celery PENDING significa literalmente
    # "no tengo registro de este id" — por eso acá no se puede responder 404.
    async_result = AsyncResult(task_id, app=celery_app)
    state = async_result.state

    response = StatusResponse(
        task_id=task_id,
        status=state,
        # ready() es False durante RETRY: la tarea sigue viva, esperando su
        # próximo intento. Ese es justo el estado que veníamos a observar.
        ready=async_result.ready(),
    )

    # En RETRY y FAILURE, .info es la EXCEPCIÓN, no un valor de retorno. Con el
    # serializador JSON viaja como {exc_type, exc_message} y Celery la
    # reconstruye de este lado; str() nos deja el mensaje.
    if state in ("RETRY", "FAILURE"):
        response.detail = str(async_result.info)
    elif state == "SUCCESS":
        response.result = async_result.result

    return response


@router.delete(
    "/{task_id}",
    response_model=RevokeResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def revoke_task(
    task_id: str,
    terminate: bool = Query(
        default=False,
        description=(
            "Matar la tarea si YA está corriendo. Sin esto, una tarea en curso "
            "termina igual y solo se cancelan las que aún no empezaron."
        ),
    ),
) -> RevokeResponse:
    """Pide cancelar una tarea.

    202 y no 200 ni 204: "aceptado, todavía no aplicado". Es lo único honesto
    que se puede responder — `revoke()` publica la orden en el broker y vuelve
    sin esperar a nadie. No sabemos si había workers escuchando, si el id
    existía ni si alguno llegó a aplicarla.

    Tampoco hay 404 posible: la revocación de un id inventado es igual de
    válida que la de uno real. Es más, revocar un id que TODAVÍA no se encoló
    funciona — el worker se acuerda de ese id y descarta el mensaje cuando
    llegue.
    """
    task_control.revoke(task_id, terminate=terminate)

    return RevokeResponse(
        task_id=task_id,
        requested=True,
        terminate=terminate,
        # Se lee inmediatamente después de mandar la orden, así que lo más
        # probable es que todavía diga PENDING o STARTED. REVOKED aparece
        # cuando el worker procesa la orden, unos milisegundos más tarde.
        status=task_control.state_of(task_id),
    )
