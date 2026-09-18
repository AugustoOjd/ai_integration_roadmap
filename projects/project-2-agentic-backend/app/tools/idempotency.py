"""Que una tool con efectos corra una sola vez, aunque la tarea corra dos.

Con `acks_late`, un worker que muere después de ejecutar pero antes de confirmar
hace que el broker le entregue la misma tarea a otro. No es una posibilidad, es
el diseño — y la tarea llama a un LLM que ejecuta tools con efectos, así que dos
veces significa dos cancelaciones, dos mails, dos cobros.

La clave es el `tool_use_id`. No un `uuid4()` generado al ejecutar: ése sería
distinto en cada corrida. El `tool_use_id` lo mandó el modelo, quedó persistido
en el historial, y por eso es **el mismo en cada reintento**.

---

**Lo que esto garantiza depende de dónde esté el efecto**, y conviene tenerlo
claro porque es la parte que más se malentiende:

- **Efecto en esta base** (`cancel_order`): la reserva y el `UPDATE` de la tool
  viven en la MISMA transacción. O commitean las dos o ninguna. La idempotencia
  es perfecta y `in_flight` nunca sobrevive.
- **Efecto afuera** (un mail, un cobro): entre reservar y que el mail salga hay
  una ventana que ninguna transacción cubre. Si el proceso muere ahí, la fila
  queda `in_flight` y **no hay forma de saber desde acá si el mail salió**.

Esa ventana no se cierra con más código: se cierra preguntándole al proveedor,
mandándole tu clave de idempotencia para que deduplique él (lo que hacen Stripe y
similares), o decidiendo por política qué se prefiere. Acá el default es negarse,
que es lo correcto para lo irreversible.
"""

import logging
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError

from app.agent.deps import AgentDeps, RunContext
from app.core.models import ToolExecution, ToolExecutionStatus
from app.tools.registry import ToolError

logger = logging.getLogger(__name__)


class EjecucionAmbiguaError(ToolError):
    """Quedó una reserva sin cerrar: no se sabe si el efecto ocurrió.

    Hereda de `ToolError` para que el loop se lo cuente al modelo en vez de matar
    la corrida. El texto está escrito para que el modelo NO reintente.
    """


def ejecutar_una_sola_vez(
    ctx: RunContext[AgentDeps],
    tool_name: str,
    ejecutar: Callable[[], str],
) -> str:
    """Corre `ejecutar()` si esta `tool_use_id` no se ejecutó antes.

    Si ya se ejecutó, devuelve **la misma salida** que la primera vez. Repetir el
    resultado importa tanto como no repetir el efecto: si la segunda corrida le
    contestara otra cosa al modelo, el historial dejaría de reproducirse igual.
    """
    db = ctx.deps.db
    tool_use_id = ctx.tool_use_id

    if tool_use_id is None:
        # Bug de programación: el loop no puso el id. Preferimos reventar a
        # ejecutar un efecto sin candado.
        raise RuntimeError(f"la tool {tool_name!r} tiene efectos y no recibió tool_use_id")

    reserva = _reservar(ctx, tool_name)

    if reserva is None:
        # Ya existía. Miramos en qué quedó.
        previa = db.get(ToolExecution, tool_use_id)
        assert previa is not None  # acabamos de chocar contra su PK

        if previa.status is ToolExecutionStatus.DONE:
            logger.info(
                "tool %s (%s) ya ejecutada, se devuelve el resultado guardado",
                tool_name,
                tool_use_id,
            )
            return previa.result or ""

        # in_flight. Alguien reservó y nunca cerró: o está corriendo ahora mismo
        # en otro worker, o murió a mitad de camino.
        #
        # El default es NEGARSE, porque para una acción irreversible el error más
        # barato es no hacerla dos veces. Para una tool donde perder es peor que
        # duplicar —una notificación, por ejemplo— la política correcta sería la
        # contraria: reejecutar. Es una decisión por tool y va escrita, no
        # heredada del framework.
        logger.error("tool %s (%s) quedó in_flight", tool_name, tool_use_id)
        raise EjecucionAmbiguaError(
            f"no se pudo confirmar si {tool_name!r} ya se ejecutó. "
            f"NO la reintentes: avisale al usuario que revise el estado antes de "
            f"volver a pedirla."
        )

    salida = ejecutar()

    reserva.status = ToolExecutionStatus.DONE
    reserva.result = salida
    reserva.completed_at = datetime.now(UTC)
    # Sin commit: esto viaja en la transacción de quien llamó, que es exactamente
    # lo que hace atómica la pareja reserva+efecto para las tools de base.
    db.flush()

    return salida


def _reservar(ctx: RunContext[AgentDeps], tool_name: str) -> ToolExecution | None:
    """Inserta la reserva. Devuelve None si esa `tool_use_id` ya estaba.

    El INSERT va adentro de un SAVEPOINT (`begin_nested`). Sin él, la
    `IntegrityError` del choque contra la PK envenena la transacción entera y
    todo lo que venga después falla con "current transaction is aborted".

    Y se usa el choque de la PK como detección en vez de un `SELECT` previo: un
    `SELECT` y un `INSERT` separados dejan una ventana en el medio por la que
    pueden pasar dos. La restricción de unicidad no tiene ventana.
    """
    db = ctx.deps.db
    try:
        with db.begin_nested():
            reserva = ToolExecution(
                tool_use_id=ctx.tool_use_id,
                conversation_id=ctx.deps.conversation_id,
                tool_name=tool_name,
            )
            db.add(reserva)
        return reserva
    except IntegrityError:
        return None
