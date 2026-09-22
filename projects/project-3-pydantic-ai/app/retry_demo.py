"""Fuerza un ModelRetry con un modelo guionado.

    uv run python -m app.retry_demo

No llama a la API. `FunctionModel` reemplaza al modelo por una función tuya que
decide qué responder en cada turno, así que podés mandar a propósito los
argumentos que el modelo real evita mandar.
"""

import asyncio
from decimal import Decimal

from pydantic_ai import DeferredToolRequests, DeferredToolResults, ToolApproved
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy import select

from app.agent.deps import Deps
from app.agent.triage import triage_agent
from app.cli import _traza
from app.core.db import SessionFactory, engine
from app.core.models import Order, OrderStatus

ORDEN = "ord_bruno_1"  # Monitor 27", total 340.00


def guion(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    """Qué contesta el "modelo" en cada vuelta.

    El turno se deduce de cuántas veces ya respondimos: la conversación entera
    llega en `messages` en cada llamada.
    """
    turno = sum(1 for m in messages if isinstance(m, ModelResponse))

    if turno == 0:
        # Más de lo que vale la orden. La tool va a levantar ModelRetry.
        return ModelResponse(parts=[ToolCallPart("refund", {"order_id": ORDEN, "amount": "500"})])

    if turno == 1:
        # Segundo intento, ya con el techo que vino en el mensaje de retry.
        return ModelResponse(parts=[ToolCallPart("refund", {"order_id": ORDEN, "amount": "340"})])

    # Cerrar el run llamando a la tool de salida, que es como el framework
    # materializa el output_type.
    return ModelResponse(
        parts=[
            ToolCallPart(
                info.output_tools[0].name,
                {
                    "category": "billing",
                    "priority": 3,
                    "needs_human": False,
                    "summary": "Reembolso total del monitor.",
                },
            )
        ]
    )


async def _reset() -> None:
    """Deja la orden sin reembolsar.

    Hace falta porque el demo NO es idempotente: `refund` escribe, y una segunda
    corrida arrancaría con restante=0. El primer intento fallaría por monto, el
    segundo también, y se agotarían los reintentos de la tool.

    Que esto sea problema tuyo y no del framework es literalmente una fila de la
    tabla "lo que sigue siendo tuyo".
    """
    async with SessionFactory() as session:
        orden = (await session.scalars(select(Order).where(Order.id == ORDEN))).one()
        orden.refunded_total = Decimal("0")
        orden.status = OrderStatus.PENDING
        await session.commit()


async def main() -> None:
    await _reset()

    # role="agent": si no, `refund` no existe en este run y el guion llama a una
    # tool que el modelo nunca habría visto.
    deps = Deps(session_factory=SessionFactory, customer_id="cus_bruno", role="agent")

    with triage_agent.override(model=FunctionModel(guion)):
        result = await triage_agent.run("reembolsá el monitor", deps=deps)

        # refund requiere aprobación, así que su cuerpo —y el ModelRetry que
        # vive adentro— no corre hasta que alguien diga que sí. Acá aprobamos
        # todo sin preguntar: lo que se demuestra es el retry, no la aprobación.
        while isinstance(result.output, DeferredToolRequests):
            results = DeferredToolResults()
            for call in result.output.approvals:
                results.approvals[call.tool_call_id] = ToolApproved()
            result = await triage_agent.run(
                message_history=result.all_messages(),
                deferred_tool_results=results,
                deps=deps,
            )

    _traza(result.all_messages())

    # Releer de la base en una sesión nueva: lo que importa es qué quedó
    # escrito, no qué dijo el modelo que hizo.
    async with SessionFactory() as session:
        orden = (await session.scalars(select(Order).where(Order.id == ORDEN))).one()

    print(
        f"\n{ORDEN}: total {orden.total} · reembolsado {orden.refunded_total} · {orden.status}"
    )
    esperado = Decimal("340.00")
    print("OK" if orden.refunded_total == esperado else f"ESPERABA {esperado}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
