"""El agente: un tipo de salida, un tipo de dependencias, un toolset filtrado."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field
from pydantic_ai import (
    Agent,
    DeferredToolRequests,
    FunctionToolset,
    ModelRetry,
    RunContext,
)
from pydantic_ai.tools import ToolDefinition
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.deps import Deps
from app.core.config import settings
from app.core.models import Order, OrderStatus


class OrderView(BaseModel):
    """Lo que la tool devuelve. Es lo que el modelo va a leer: sin campos de más."""

    id: str
    description: str
    total: Decimal
    refunded_total: Decimal
    status: str
    placed_at: datetime


class Triage(BaseModel):
    """El resultado del run. No es un string que haya que parsear."""

    category: Literal["billing", "shipping", "technical"]

    # Field(ge=…, le=…) viaja al JSON Schema y además se valida de vuelta: si el
    # modelo contesta 9, el run no termina con un 9.
    priority: int = Field(ge=1, le=5, description="1 = trivial, 5 = urgente")

    needs_human: bool
    summary: str = Field(description="Una o dos oraciones, en español")


# Las tools ya no cuelgan del agente: viven en un toolset, que es un valor que
# se puede filtrar, prefijar, combinar o envolver antes de dárselo al agente.
soporte = FunctionToolset[Deps]()


@soporte.tool
async def recent_orders(ctx: RunContext[Deps], limit: int = 5) -> list[OrderView]:
    """Lista las órdenes más recientes del cliente.

    Args:
        limit: Cuántas traer, de la más nueva a la más vieja.
    """
    # El filtro por cliente sale de ctx.deps, no de un argumento: el modelo puede
    # pedir limit=3, no puede pedir las de otro.
    stmt = (
        select(Order)
        .where(Order.customer_id == ctx.deps.customer_id)
        .order_by(Order.placed_at.desc())
        .limit(limit)
    )
    async with ctx.deps.session_factory() as session:
        rows = (await session.scalars(stmt)).all()
    return [OrderView.model_validate(o, from_attributes=True) for o in rows]


async def _orden_del_cliente(session: AsyncSession, ctx: RunContext[Deps], order_id: str) -> Order:
    """Carga una orden exigiendo que sea de este cliente.

    `order_id` sí es un argumento, así que el modelo puede nombrarlo — y por lo
    tanto puede inventarlo. El filtro por customer_id va en el WHERE.

    Una orden ajena da el mismo mensaje que una inexistente: confirmar que
    `ord_carla_1` existe ya sería filtrar algo.
    """
    stmt = select(Order).where(
        Order.id == order_id,
        Order.customer_id == ctx.deps.customer_id,
    )
    order = (await session.scalars(stmt)).one_or_none()
    if order is None:
        raise ModelRetry(f"No existe la orden {order_id} para este cliente.")
    return order


@soporte.tool(requires_approval=True)
async def refund(
    ctx: RunContext[Deps],
    order_id: str,
    # Annotated[..., Field(gt=0)] se valida ANTES de entrar acá: un monto
    # negativo nunca ejecuta una línea de esta función.
    amount: Annotated[Decimal, Field(gt=0)],
) -> str:
    """Reembolsa, total o parcialmente, una orden del cliente.

    Args:
        order_id: El id de la orden, como aparece en recent_orders.
        amount: Cuánto reembolsar. No puede superar lo que queda por reembolsar.
    """
    async with ctx.deps.session_factory() as session:
        order = await _orden_del_cliente(session, ctx, order_id)

        if order.status is OrderStatus.CANCELLED:
            raise ModelRetry(
                f"La orden {order_id} está cancelada: no hay qué reembolsar."
            )

        restante = order.total - order.refunded_total
        if amount > restante:
            # ModelRetry y no ValueError: el modelo recibe este texto como un
            # turno más y puede volver a llamar con el monto correcto.
            raise ModelRetry(
                f"El máximo reembolsable de {order_id} es {restante}, no {amount}."
            )

        order.refunded_total += amount
        if order.refunded_total == order.total:
            order.status = OrderStatus.REFUNDED

        # Commit acá y no al final del run: el reembolso ya ocurrió y no debe
        # deshacerse porque una vuelta posterior falle.
        await session.commit()

        return f"Reembolsados {amount} de {order_id}. Quedan {order.total - order.refunded_total}."


# Qué tools pueden reembolsar, por nombre. Vivir acá y no adentro de refund()
# es el punto: la lista de tools sensibles es una decisión de negocio, y se lee
# de un vistazo en vez de estar repartida entre los cuerpos de las funciones.
SOLO_SOPORTE = {"refund"}


def _visible(ctx: RunContext[Deps], tool: ToolDefinition) -> bool:
    """Se evalúa por run, antes de armar el request: decide qué existe."""
    if tool.name in SOLO_SOPORTE:
        return ctx.deps.role == "agent"
    return True


# filtered() devuelve otro toolset, no muta el original: `soporte` sigue entero
# por si otro agente lo quiere completo. Con nombre propio para poder componerlo
# con otros toolsets sin repetir el filtro.
TOOLSET = soporte.filtered(_visible)


triage_agent = Agent(
    settings.AGENT_MODEL,
    deps_type=Deps,
    # Dos salidas posibles. Que el run haya quedado esperando una aprobación no
    # es un flag ni una excepción: es el otro miembro de la unión, y el type
    # checker te obliga a contemplarlo.
    output_type=[Triage, DeferredToolRequests],
    toolsets=[TOOLSET],
    instructions=(
        "Clasificás tickets de soporte. Consultá las órdenes del cliente antes "
        "de decidir. Si pide un reembolso y tenés cómo hacerlo, ejecutalo; si no "
        "tenés esa herramienta, marcá needs_human. "
        "Sé breve y no inventes datos que no viste."
    ),
)
