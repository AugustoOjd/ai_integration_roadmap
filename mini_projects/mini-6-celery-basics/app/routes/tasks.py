from celery.result import AsyncResult
from fastapi import APIRouter, HTTPException, Response, status

from app.celery_app import celery_app
from app.schemas import (
    EnqueueRequest,
    EnqueueResponse,
    FlakyRequest,
    ResultResponse,
    StatusResponse,
)
from app.tasks import flaky, slow_double

router = APIRouter(prefix="/tasks", tags=["tasks"])


# Endpoints SIN async: todo lo de abajo habla con Redis por socket bloqueante
# (delay, AsyncResult). Declarados sync, FastAPI los corre en su threadpool y
# no bloquean el event loop; con `async def` sí lo harían.
@router.post("/enqueue", response_model=EnqueueResponse, status_code=status.HTTP_202_ACCEPTED)
def enqueue_task(payload: EnqueueRequest) -> EnqueueResponse:
    """Encola y responde de inmediato. 202 = aceptado, aún no procesado."""
    # .delay() es el atajo de .apply_async(): serializa los args a JSON, hace
    # LPUSH en la cola y devuelve un AsyncResult sin esperar al worker.
    async_result = slow_double.delay(payload.value)
    return EnqueueResponse(task_id=async_result.id, status=async_result.state)


@router.post("/flaky", response_model=EnqueueResponse, status_code=status.HTTP_202_ACCEPTED)
def enqueue_flaky(payload: FlakyRequest) -> EnqueueResponse:
    """Encola una tarea que falla y reintenta, para observar RETRY y FAILURE."""
    async_result = flaky.delay(payload.fail_times)
    return EnqueueResponse(task_id=async_result.id, status=async_result.state)


@router.get("/{task_id}/status", response_model=StatusResponse)
def get_task_status(task_id: str) -> StatusResponse:
    # AsyncResult solo lee el backend; no reencola ni valida nada. Un task_id
    # inventado devuelve PENDING, que en Celery significa "no sé nada de este
    # id" — por eso no podemos responder 404 aquí.
    async_result = AsyncResult(task_id, app=celery_app)
    return StatusResponse(
        task_id=task_id,
        status=async_result.state,
        ready=async_result.ready(),
    )


@router.get("/{task_id}/result", response_model=ResultResponse)
def get_task_result(task_id: str, response: Response) -> ResultResponse:
    """Devuelve el resultado si está listo. Nunca bloquea esperando."""
    async_result = AsyncResult(task_id, app=celery_app)

    # Nada de .get() ni .result a secas: ambos bloquean hasta que la tarea
    # termine, ocupando un hilo del pool por cliente que consulte.
    if not async_result.ready():
        response.status_code = status.HTTP_202_ACCEPTED
        return ResultResponse(task_id=task_id, status=async_result.state)

    if async_result.failed():
        # En FAILURE, .result es la excepción que levantó la tarea, no un valor.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Task failed: {async_result.result}",
        )

    return ResultResponse(
        task_id=task_id,
        status=async_result.state,
        result=async_result.result,
    )
