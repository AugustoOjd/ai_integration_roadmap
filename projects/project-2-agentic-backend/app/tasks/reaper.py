"""El que se da cuenta de que un worker se murió.

Un deploy, un OOM, un SIGKILL. La tarea estaba en la vuelta 2. Nadie va a moverla
de `running`, porque el único que podía está muerto.

**Primero la buena noticia, y es grande: la conversación no queda rota.** El turno
se guarda entero en una transacción, así que un worker que muere en la vuelta 2
nunca commiteó nada de ese turno. No hay `tool_use` huérfano en `messages`.
Quedan filas sueltas en `execution_steps` —y está bien, son auditoría: querés
saber qué alcanzó a hacer antes de morirse.

**Lo que sí queda mal es la fila en `running` para siempre.** Y acá hay una
sutileza que vale entender, porque explica por qué este archivo existe:

Con `acks_late` + `task_reject_on_worker_lost`, el broker **ya reentrega** el
mensaje a otro worker. Eso pasa solo. Pero ese worker nuevo entra, ve la fila en
`running`, y el candado de idempotencia lo hace irse sin tocar nada — que es
exactamente lo correcto contra el trabajo duplicado.

O sea: la reentrega ocurre y se descarta. La fila queda huérfana igual. El
reaper cierra justamente ese hueco.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app.agent.repository import expirar_vencidas
from app.core.config import settings
from app.core.db import SessionFactory
from app.core.models import Conversation, ConversationStatus, Task, TaskStatus, UserBudget
from app.tasks.celery_app import celery_app
from app.tasks.state import marcar_fallida

logger = logging.getLogger(__name__)

# La razón de fallo, distinguible de cualquier otra en un `where`. Una tarea que
# murió con el worker no es lo mismo que una que falló sola, y mezclarlas en un
# `error` de texto libre hace imposible contar cuántas veces se cayó el cluster.
RAZON_WORKER_PERDIDO = "worker_lost: sin latido desde hace más de"


@celery_app.task(name="agent.reap_stale")
def reap_stale_tasks() -> int:
    """Cierra las tareas cuyo worker dejó de latir. Devuelve cuántas.

    El umbral tiene que ser **bastante mayor que la vuelta más lenta que
    esperás**. Si es muy corto, matás tareas vivas que estaban esperando una
    respuesta larga del modelo; si es muy largo, las huérfanas tardan en
    aparecer. Entre los dos errores, el segundo es barato.
    """
    limite = datetime.now(UTC) - timedelta(seconds=settings.TAREA_SIN_LATIDO_S)

    with SessionFactory() as db:
        colgadas = (
            db.execute(
                select(Task.id).where(
                    Task.status == TaskStatus.RUNNING,
                    # `heartbeat_at IS NULL` también cuenta: es una tarea que pasó
                    # a `running` y murió antes de la primera vuelta.
                    (Task.heartbeat_at.is_(None)) | (Task.heartbeat_at < limite),
                    Task.started_at < limite,
                )
            )
            .scalars()
            .all()
        )

        for task_id in colgadas:
            # El CAS decide: si entre el SELECT y esto el worker revivió y la
            # movió, no prende y no la pisamos.
            if marcar_fallida(
                db, task_id, f"{RAZON_WORKER_PERDIDO} {settings.TAREA_SIN_LATIDO_S}s"
            ):
                logger.error("tarea id=%s reapeada: el worker dejó de latir", task_id)

    if colgadas:
        # Esta métrica es la señal de que algo anda mal en el cluster, no en el
        # código. Un reaper que no reapea nunca es lo normal; uno que reapea todos
        # los días está diciendo que los workers se caen todos los días.
        logger.warning("reaper: %d tareas cerradas por falta de latido", len(colgadas))

    return len(colgadas)


@celery_app.task(name="agent.expire_approvals")
def expire_pending_approvals() -> int:
    """Cierra las aprobaciones que nadie decidió a tiempo. Devuelve cuántas.

    Con un humano mirando el 202 esto era una molestia; **sin nadie mirando, se
    acumulan**. Un pendiente de hace una semana sigue siendo aprobable: alguien
    autoriza el martes un "cancelá el pedido 991" que el agente propuso el
    viernes, cuando el pedido ya se entregó.

    La tarea que estaba esperando también se cierra: si el permiso venció, esa
    corrida no va a terminar nunca. Queda en `failed` con la razón — no en
    `cancelled`, porque nadie la canceló: se quedó sin respuesta.
    """
    with SessionFactory() as db:
        vencidas = expirar_vencidas(db)

        for aprobacion in vencidas:
            logger.warning(
                "aprobación vencida tool_use=%s tool=%s conversation=%s",
                aprobacion.tool_use_id,
                aprobacion.tool_name,
                aprobacion.conversation_id,
            )
            if aprobacion.task_id:
                marcar_fallida(
                    db,
                    aprobacion.task_id,
                    f"approval_expired: nadie decidió sobre {aprobacion.tool_name!r} a tiempo",
                )

        # La conversación vuelve a aceptar mensajes: lo que la tenía frenada ya no
        # se puede resolver.
        for aprobacion in vencidas:
            conversacion = db.get(Conversation, aprobacion.conversation_id)
            if conversacion and conversacion.status is ConversationStatus.PENDING_APPROVAL:
                conversacion.status = ConversationStatus.ACTIVE
        if vencidas:
            db.commit()

    return len(vencidas)


@celery_app.task(name="agent.sweep_reservations")
def sweep_stale_reservations() -> int:
    """Libera reservas de presupuesto que quedaron colgadas. Devuelve cuántas filas.

    Una reserva se aparta antes de llamar al modelo y se liquida después. El loop
    la devuelve solo si la llamada falla — pero si el proceso muere **entre las
    dos cosas**, nadie la devuelve: quedan tokens apartados por una llamada que
    ya no existe, y el usuario los pierde hasta que la ventana cambie de hora.

    Cómo se detecta sin llevar un registro por tarea: **si el usuario no tiene
    ninguna tarea corriendo, no puede haber ninguna reserva legítima abierta.**
    En reposo, `tokens_reserved` tiene que ser 0. Cualquier otro valor es basura.
    """
    with SessionFactory() as db:
        resultado = db.execute(
            update(UserBudget)
            .where(
                UserBudget.tokens_reserved > 0,
                ~select(Task.id)
                .join(Conversation, Conversation.id == Task.conversation_id)
                .where(
                    Conversation.user_id == UserBudget.user_id,
                    Task.status == TaskStatus.RUNNING,
                )
                .exists(),
            )
            .values(tokens_reserved=0)
            .execution_options(synchronize_session=False)
        )
        db.commit()

    if resultado.rowcount:
        logger.warning(
            "reaper: %d presupuestos con reservas huérfanas liberados", resultado.rowcount
        )
    return resultado.rowcount
