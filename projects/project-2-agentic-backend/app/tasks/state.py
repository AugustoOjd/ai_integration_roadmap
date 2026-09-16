"""La máquina de estados de una tarea, en un solo lugar.

Un `status` que cada endpoint asigna a mano es un `status` que en algún momento
va a tener un valor que nadie sabe cómo llegó ahí. Acá las transiciones son datos
y el resto del código pide movimientos, no asigna valores.

    pending ──> running ──> success
            │           ├──> failed
            │           └──> pending_approval ──> success | failed
            └──> failed      (la conversación estaba pausada o sin presupuesto)

`success` y `failed` son terminales: una tarea que terminó no vuelve a moverse.
Eso no es una convención, es lo que impide que un reintento tardío pise el
resultado de una corrida que ya cerró.

Las transiciones son **compare-and-swap**: la condición viaja adentro del UPDATE
y la base arbitra. Con la API y varios workers escribiendo la misma fila, leer y
después escribir deja una ventana en el medio donde otro puede haberla movido.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.models import Task, TaskStatus


class TaskNotFoundError(LookupError):
    """No existe una tarea con ese id. Se traduce a 404."""


# Qué se puede hacer desde cada estado. Un frozenset vacío es un estado terminal.
TRANSICIONES: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.PENDING: frozenset({TaskStatus.RUNNING, TaskStatus.FAILED}),
    TaskStatus.RUNNING: frozenset(
        {TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.PENDING_APPROVAL}
    ),
    TaskStatus.PENDING_APPROVAL: frozenset({TaskStatus.SUCCESS, TaskStatus.FAILED}),
    TaskStatus.SUCCESS: frozenset(),
    TaskStatus.FAILED: frozenset(),
}

# La vuelta: desde qué estados se puede llegar a cada uno. Es lo que necesita el
# `WHERE` del UPDATE, y se DERIVA de la tabla de arriba en vez de escribirse
# aparte — dos listas que dicen lo mismo son dos listas que un día no lo dicen.
_ORIGENES: dict[TaskStatus, frozenset[TaskStatus]] = {
    destino: frozenset(
        origen for origen, destinos in TRANSICIONES.items() if destino in destinos
    )
    for destino in TaskStatus
}


def _transicionar(db: Session, task_id: str, nuevo: TaskStatus, **campos: Any) -> bool:
    """Mueve la tarea si está en un estado desde el que se puede. Dice si prendió.

    La condición va adentro del UPDATE:

        UPDATE tasks SET status = 'running'
        WHERE id = :id AND status IN ('pending')

    Si afecta cero filas, o la tarea no existe o alguien la movió primero. Eso no
    es un error: es información, y quien llama decide qué significa. Para
    `pending -> running` significa "otro worker ya la tomó, no la reproceses";
    para `running -> success` significa que algo raro pasó y hay que mirarlo.

    Devuelve un bool y no levanta a propósito. Una excepción obligaría a envolver
    en `try` el camino normal de la idempotencia, que no es excepcional: es el
    caso esperado cada vez que el broker reentrega una tarea.
    """
    resultado = db.execute(
        update(Task)
        .where(Task.id == task_id, Task.status.in_(_ORIGENES[nuevo]))
        .values(status=nuevo, **campos)
        # La sesión puede tener el objeto cargado; no le pedimos a SQLAlchemy que
        # lo sincronice porque quien llama trabaja con el `task_id`, no con la
        # instancia. Sincronizar sería una query extra para nada.
        .execution_options(synchronize_session=False)
    )
    db.commit()
    return resultado.rowcount == 1


# Los timestamps viajan con la transición y no se setean por separado: un
# `started_at` que se puede escribir sin pasar a `running` es un dato que en
# algún momento va a contradecir al status.


def marcar_corriendo(db: Session, task_id: str) -> bool:
    """`pending -> running`. False si otro la tomó primero.

    Éste es el candado contra el trabajo duplicado: una tarea que arranca y no
    logra prender este UPDATE es una tarea que ya está corriendo en otro lado.
    """
    return _transicionar(db, task_id, TaskStatus.RUNNING, started_at=datetime.now(UTC))


def marcar_exitosa(db: Session, task_id: str, result: dict[str, Any]) -> bool:
    return _transicionar(
        db, task_id, TaskStatus.SUCCESS, result=result, finished_at=datetime.now(UTC)
    )


def marcar_fallida(db: Session, task_id: str, error: str) -> bool:
    # El error se recorta: puede venir de una excepción con un repr enorme, y esta
    # columna la lee un humano en un listado.
    return _transicionar(
        db, task_id, TaskStatus.FAILED, error=error[:2_000], finished_at=datetime.now(UTC)
    )


def marcar_esperando_aprobacion(db: Session, task_id: str) -> bool:
    """La corrida se frenó esperando a un humano.

    Sin `finished_at`: la tarea no terminó, está detenida. La diferencia importa
    para cualquier métrica de duración — si acá pusiéramos un timestamp, el
    tiempo que alguien tardó en aprobar contaría como tiempo de ejecución.
    """
    return _transicionar(db, task_id, TaskStatus.PENDING_APPROVAL)


def registrar_reintento(db: Session, task_id: str, intento: int) -> None:
    """Deja el contador de reintentos en la fila. No cambia el estado.

    Una tarea reintentando sigue en `running`: el reintento es del mensaje, no de
    la ejecución de negocio. Por eso esto es un UPDATE suelto y no una transición.
    """
    db.execute(
        update(Task).where(Task.id == task_id).values(retries=intento)
        .execution_options(synchronize_session=False)
    )
    db.commit()


def existe(db: Session, task_id: str) -> bool:
    """¿Hay una fila con ese id?

    Sirve para distinguir los dos motivos por los que un CAS puede no prender:
    la tarea no existe, o existe y está en otro estado. Son cosas distintas y se
    responden distinto.
    """
    return db.get(Task, task_id) is not None
