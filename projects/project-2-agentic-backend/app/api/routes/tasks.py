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

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import select

from app.agent.budget import BudgetExceededError, estado_usuario
from app.agent.deps import CurrentUser
from app.agent.loop import ApprovalRequired
from app.agent.repository import (
    ConversationPausedError,
    decidir_aprobacion,
    get_conversation,
    load_task_steps,
    pendientes_de_tarea,
)
from app.api.schemas.conversations import ApprovalDecision
from app.api.schemas.tasks import (
    CreateTaskRequest,
    PendingApprovalResponse,
    TaskResponse,
    TaskStepResponse,
)
from app.core.db import Db
from app.core.models import (
    Conversation,
    ConversationStatus,
    ExecutionStep,
    PendingApproval,
    Task,
    TaskStatus,
)
from app.tasks.agent_tasks import execute_agent_task, resume_agent_task
from app.tasks.state import (
    TaskNotFoundError,
    marcar_cancelada,
    marcar_retomando,
    pedir_cancelacion,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["tasks"])


def _a_response(
    tarea: Task,
    pasos: list[ExecutionStep] | None = None,
    pendientes: list[PendingApproval] | None = None,
) -> TaskResponse:
    """Proyecta la fila al contrato público.

    El id se expone como `task_id` y no como `id`: en un cliente que maneja
    conversaciones y tareas a la vez, un campo llamado `id` a secas obliga a
    recordar de qué era.

    `pasos` sólo se pasa donde interesa el progreso. El listado no los trae: son
    N queries para una pregunta que el listado no contesta.
    """
    pasos = pasos or []
    return TaskResponse(
        task_id=tarea.id,
        conversation_id=tarea.conversation_id,
        status=tarea.status,
        result=tarea.result,
        error=tarea.error,
        created_at=tarea.created_at,
        started_at=tarea.started_at,
        finished_at=tarea.finished_at,
        # La vuelta actual es la del último paso. Derivado, no guardado.
        iteration=pasos[-1].iteration if pasos else None,
        steps=[TaskStepResponse.model_validate(p) for p in pasos],
        pending_approvals=[
            PendingApprovalResponse.model_validate(a) for a in (pendientes or [])
        ],
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
def ver_tarea(task_id: str, db: Db, user_id: CurrentUser, response: Response) -> TaskResponse:
    """En qué quedó una tarea, y qué está haciendo ahora.

    Éste es el único canal. El request que la creó se fue hace rato: el resultado,
    el error, la pausa y el progreso se cuentan acá o no se cuentan.

    El filtro por dueño va contra la conversación: la tarea no guarda `user_id`
    propio, así que el permiso se resuelve por el hilo al que pertenece.
    """
    tarea = db.get(Task, task_id)
    if tarea is None:
        raise TaskNotFoundError(task_id)

    # El chequeo de dueño usa el repositorio, que ya falla como "no existe" en vez
    # de "no es tuya".
    get_conversation(db, tarea.conversation_id, user_id=user_id)

    pasos = load_task_steps(db, task_id)
    # Sólo se consulta si hace falta: en el 95% de los casos la tarea no está
    # pausada y sería una query para devolver una lista vacía.
    pendientes = (
        pendientes_de_tarea(db, task_id)
        if tarea.status is TaskStatus.PENDING_APPROVAL
        else []
    )

    # Retry-After mientras no terminó. Sin esto, un cliente que hace polling elige
    # el intervalo por su cuenta y suele elegir mal: cada 100 ms son diez queries
    # por segundo para una tarea que tarda ocho.
    #
    # Es una sugerencia, no un contrato — el cliente puede ignorarla. Pero decirle
    # cuánto esperar es más barato que descubrir después por qué la base está
    # saturada.
    if tarea.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
        response.headers["Retry-After"] = "2"

    return _a_response(tarea, pasos, pendientes)


@router.post(
    "/tasks/{task_id}/approvals/{tool_use_id}",
    response_model=TaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Aprueba o rechaza una tool sensible y reencola la corrida",
    responses={
        409: {"description": "Ya se decidió, o el pedido venció"},
        404: {"description": "No hay una aprobación pendiente con ese id"},
    },
)
def decidir(
    task_id: str,
    tool_use_id: str,
    decision: ApprovalDecision,
    db: Db,
    user_id: CurrentUser,
) -> TaskResponse:
    """Registra la decisión y **encola** la retoma. No espera al agente.

    Acá está la diferencia con el endpoint de `/conversations`, que hace lo mismo
    de forma sincrónica: éste devuelve 202 en milisegundos y el trabajo sigue en
    un worker. Que el request no espere es lo que impide que una aprobación
    ocupe un worker mientras el agente corre.

    El orden importa y no es negociable:

    1. **Se decide primero**, con un CAS sobre la fila de la aprobación. Dos POST
       simultáneos no pueden encolar dos retomas, porque el segundo no prende.
    2. La tarea vuelve de `pending_approval` a `running`. Es la MISMA tarea: el
       usuario pidió una cosa y sigue poleando un solo id.
    3. Recién ahí se encola.

    Si el proceso muere entre 1 y 3, la decisión ya es durable y la tarea queda en
    `running` sin nadie corriéndola — que es exactamente lo que el reaper levanta.
    """
    tarea = db.get(Task, task_id)
    if tarea is None:
        raise TaskNotFoundError(task_id)

    get_conversation(db, tarea.conversation_id, user_id=user_id)

    # El candado: si ya se decidió o venció, esto levanta y nunca se encola nada.
    decidir_aprobacion(
        db, tarea.conversation_id, tool_use_id, approved=decision.approved
    )

    # ¿Queda otra tool sensible del mismo turno sin decidir? Los tool_result van
    # todos en un mensaje, así que no se puede retomar hasta que estén todas.
    restantes = [
        p for p in pendientes_de_tarea(db, task_id) if p.tool_use_id != tool_use_id
    ]
    if restantes:
        raise ApprovalRequired(tarea.conversation_id, restantes)

    if not marcar_retomando(db, task_id):
        logger.error("tarea id=%s: no se pudo volver a running", task_id)
    else:
        resume_agent_task.delay(task_id, tool_use_id)
        logger.info(
            "decisión id=%s tool_use=%s aprobada=%s, retoma encolada",
            task_id, tool_use_id, decision.approved,
        )

    db.expire_all()
    tarea = db.get(Task, task_id)
    assert tarea is not None
    return _a_response(tarea, load_task_steps(db, task_id))


@router.post(
    "/tasks/{task_id}/cancel",
    response_model=TaskResponse,
    summary="Pide cancelar una tarea",
)
def cancelar_tarea(task_id: str, db: Db, user_id: CurrentUser) -> TaskResponse:
    """Pide la cancelación. **Idempotente**: llamarlo dos veces devuelve 200.

    Cancelar dos veces no es un conflicto — es alguien que hizo doble click, o un
    cliente con retry. La segunda llamada no tiene nada que hacer y no tiene nada
    que reportar: 200 con el estado actual.

    Lo que hace depende de dónde esté la tarea, y son tres casos distintos:

    - **`pending`** — nunca arrancó. Se cancela en el acto con un CAS: cuando el
      worker la levante, el `marcar_corriendo` no va a prender y se va a ir sola.
    - **`pending_approval`** — está detenida esperando a un humano. No hay ningún
      loop corriendo que pueda leer el flag, así que también se cancela en el acto.
    - **`running`** — hay un loop vivo. Se prende el flag y él corta en el próximo
      punto seguro. No se puede hacer más rápido sin romper el historial.

    Una tarea ya terminada no se toca: `success`, `failed` y `cancelled` son
    terminales, y el CAS se encarga de que un pedido tardío no las mueva.
    """
    tarea = db.get(Task, task_id)
    if tarea is None:
        raise TaskNotFoundError(task_id)

    get_conversation(db, tarea.conversation_id, user_id=user_id)

    if tarea.status in (TaskStatus.PENDING, TaskStatus.PENDING_APPROVAL):
        # Nadie está corriendo: se cierra acá mismo.
        marcar_cancelada(db, task_id)
    elif tarea.status is TaskStatus.RUNNING:
        # Hay un loop vivo. Esto es una señal, no una acción.
        pedir_cancelacion(db, task_id)
        logger.info("cancelación pedida para id=%s", task_id)

    # Se relee para devolver el estado real, que puede haber cambiado por el CAS
    # de arriba o por el worker entre medio.
    db.expire_all()
    tarea = db.get(Task, task_id)
    assert tarea is not None
    return _a_response(tarea, load_task_steps(db, task_id))


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


@router.get("/users/me/budget", summary="Cuánto le queda al usuario en esta ventana")
def ver_presupuesto(db: Db, user_id: CurrentUser) -> dict[str, int | str]:
    """El presupuesto de QUIEN PREGUNTA, no de quien se nombre en la URL.

    Por eso la ruta dice `me` y no `{user_id}`: un endpoint que acepta un id de
    usuario es un endpoint donde hay que acordarse de verificar que sea el tuyo, y
    el día que alguien se olvide es una filtración. Con `me` no hay nada que
    verificar — el id sale del canal autenticado y no hay otra forma de pedirlo.

    Es la misma regla que la de las tools: lo que define permisos no viaja por un
    canal que la otra punta controla.
    """
    return estado_usuario(db, user_id)
