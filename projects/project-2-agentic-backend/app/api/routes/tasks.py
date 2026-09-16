"""Los endpoints de tareas.

    POST /conversations/{id}/tasks   crear una ejecución y encolarla
    GET  /tasks/{id}                 en qué quedó
    GET  /tasks?status=running       el listado

El `POST` devuelve en milisegundos con la tarea en `pending`: el agente corre en
un worker. Lo único que cambió respecto de la fase anterior es **quién llama a
`run_agent`** — y esa línea de diferencia es la que hace que ahora no haya a
quién devolverle un error, un resultado ni un pedido de aprobación.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Query, status
from sqlalchemy import select

from app.agent.budget import BudgetExceededError
from app.agent.deps import CurrentUser
from app.agent.repository import ConversationPausedError, get_conversation
from app.api.schemas.tasks import CreateTaskRequest, TaskResponse
from app.core.db import Db
from app.core.models import Conversation, ConversationStatus, Task, TaskStatus
from app.tasks.agent_tasks import execute_agent_task
from app.tasks.state import TaskNotFoundError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["tasks"])


def _a_response(tarea: Task) -> TaskResponse:
    """Proyecta la fila al contrato público.

    El id se expone como `task_id` y no como `id`: en un cliente que maneja
    conversaciones y tareas a la vez, un campo llamado `id` a secas obliga a
    recordar de qué era.
    """
    return TaskResponse(
        task_id=tarea.id,
        conversation_id=tarea.conversation_id,
        status=tarea.status,
        result=tarea.result,
        error=tarea.error,
        created_at=tarea.created_at,
        started_at=tarea.started_at,
        finished_at=tarea.finished_at,
    )


@router.post(
    "/conversations/{conversation_id}/tasks",
    response_model=TaskResponse,
    # 202 y no 201. El 201 diría "creé el recurso, acá está" — y lo que devolvemos
    # no es el resultado sino una promesa: la tarea existe y todavía no corrió.
    # 202 Accepted es exactamente eso, y le dice al cliente que tiene que volver
    # a preguntar.
    status_code=status.HTTP_202_ACCEPTED,
    summary="Crea una tarea y la encola",
    responses={
        409: {"description": "La conversación ya está esperando una aprobación"},
        402: {"description": "La conversación se quedó sin presupuesto"},
    },
)
def crear_tarea(
    conversation_id: str, request: CreateTaskRequest, db: Db, user_id: CurrentUser
) -> TaskResponse:
    """Crea la fila y la encola. No espera al agente."""
    conversacion = get_conversation(db, conversation_id, user_id=user_id)

    # Los dos rechazos baratos, antes de crear nada: una tarea que nace muerta es
    # una fila que después hay que explicar.
    if conversacion.status is ConversationStatus.PENDING_APPROVAL:
        raise ConversationPausedError(conversacion.id)
    if conversacion.status is ConversationStatus.EXHAUSTED:
        raise BudgetExceededError(
            necesarios=0,
            disponibles=max(0, conversacion.budget_tokens - conversacion.input_tokens_used),
        )

    tarea = Task(conversation_id=conversacion.id, prompt=request.prompt)
    db.add(tarea)

    # El commit va ANTES del encolado, y el orden no es negociable: `.delay()`
    # puede hacer que un worker tome la tarea en el milisegundo siguiente, y si
    # la fila todavía no está visible, ese worker no la encuentra y la descarta.
    # Encolar algo que nadie va a poder leer es peor que no encolarlo.
    db.commit()
    task_id = tarea.id

    # Lo único que viaja es el id. El resto —dueño, prompt, presupuesto— lo
    # reconstruye el worker de la base: el payload cruza un broker que cualquiera
    # con acceso puede leer.
    execute_agent_task.delay(task_id)

    logger.info("tarea encolada id=%s conversation=%s", task_id, conversacion.id)

    # Devuelve en milisegundos, con la tarea en `pending`. A partir de acá el
    # estado de esta fila es el único canal: no hay a quién devolverle el
    # resultado, ni el error, ni el pedido de aprobación.
    return _a_response(tarea)


@router.get("/tasks/{task_id}", response_model=TaskResponse, summary="Estado de una tarea")
def ver_tarea(task_id: str, db: Db, user_id: CurrentUser) -> TaskResponse:
    """En qué quedó una tarea.

    El filtro por dueño va en la misma query, con un join a la conversación: la
    tarea no guarda `user_id` propio, así que el permiso se resuelve por el hilo
    al que pertenece.
    """
    tarea = db.get(Task, task_id)
    if tarea is None:
        raise TaskNotFoundError(task_id)

    # El chequeo de dueño va contra la conversación y usa el repositorio, que ya
    # falla como "no existe" en vez de "no es tuya".
    get_conversation(db, tarea.conversation_id, user_id=user_id)

    return _a_response(tarea)


@router.get("/tasks", response_model=list[TaskResponse], summary="Listado de tareas")
def listar_tareas(
    db: Db,
    user_id: CurrentUser,
    task_status: Annotated[TaskStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[TaskResponse]:
    """Las tareas del usuario, más nueva primero.

    El filtro por dueño es un join contra `conversations`, no un `user_id` en la
    tarea: una sola columna decide de quién es cada cosa.
    """
    consulta = (
        select(Task)
        .join(Conversation, Conversation.id == Task.conversation_id)
        .where(Conversation.user_id == user_id)
        .order_by(Task.created_at.desc())
        .limit(limit)
    )
    if task_status is not None:
        consulta = consulta.where(Task.status == task_status)

    return [_a_response(t) for t in db.execute(consulta).scalars().all()]
