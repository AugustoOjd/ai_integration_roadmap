from celery.result import AsyncResult
from fastapi import APIRouter, status

from app.celery_app import celery_app
from app.schemas import EnqueueResponse, FetchRequest, FlakyRequest, StatusResponse
from app.tasks import fetch_resource, flaky

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
