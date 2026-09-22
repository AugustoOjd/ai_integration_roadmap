"""El motor sin agente arriba: un grafo propio.

    uv run python -m app.graph_demo

`pydantic-graph` es el paquete que Pydantic AI usa por dentro (la Fase 8 lo
mostró). Suelto sirve para flujos donde vos decidís los pasos, no el modelo.

El ejemplo es el reembolso, pero con la decisión sacada del LLM: las mismas
reglas de `refund`, expresadas como pasos y aristas.
"""

import asyncio
from dataclasses import dataclass
from decimal import Decimal

from pydantic_graph import GraphBuilder, StepContext


@dataclass
class Estado:
    """Mutable y compartido: cada paso lo lee y lo escribe vía ctx.state."""

    total: Decimal
    reembolsado: Decimal = Decimal("0")
    cancelada: bool = False


# Los tipos de salida de `validar` son las aristas: el grafo se ramifica según
# cuál de los dos devuelve, no según un if que lea un flag.
@dataclass
class Aprobado:
    monto: Decimal


@dataclass
class Rechazado:
    motivo: str


builder = GraphBuilder(state_type=Estado, input_type=Decimal, output_type=str)


@builder.step
async def validar(ctx: StepContext[Estado, None, Decimal]) -> Aprobado | Rechazado:
    """Las mismas reglas que la tool refund, sin modelo de por medio."""
    if ctx.state.cancelada:
        return Rechazado("la orden está cancelada")

    restante = ctx.state.total - ctx.state.reembolsado
    if restante <= 0:
        return Rechazado("ya fue reembolsada por completo")

    # Recortar en vez de rechazar: acá no hay a quién pedirle que reintente.
    return Aprobado(min(ctx.inputs, restante))


@builder.step
async def aplicar(ctx: StepContext[Estado, None, Aprobado]) -> str:
    ctx.state.reembolsado += ctx.inputs.monto
    return f"reembolsado {ctx.inputs.monto}"


@builder.step
async def escalar(ctx: StepContext[Estado, None, Rechazado]) -> str:
    return f"a un humano: {ctx.inputs.motivo}"


# El nodo de decisión rutea por tipo. No ejecuta nada: elige la arista.
decidir = (
    builder.decision(note="¿se puede reembolsar?")
    .branch(builder.match(Aprobado).to(aplicar))
    .branch(builder.match(Rechazado).to(escalar))
)

builder.add(
    builder.edge_from(builder.start_node).to(validar),
    builder.edge_from(validar).to(decidir),
    # Los dos caminos terminan el grafo.
    builder.edge_from(aplicar, escalar).to(builder.end_node),
)

# build() valida la estructura: un nodo inalcanzable o una arista que falta
# fallan acá, no en la primera corrida.
graph = builder.build()


CASOS = [
    ("pide de más", Decimal("500"), Estado(total=Decimal("340"))),
    ("parcial", Decimal("40"), Estado(total=Decimal("340"))),
    ("ya reembolsada", Decimal("10"), Estado(Decimal("340"), Decimal("340"))),
    ("cancelada", Decimal("50"), Estado(Decimal("340"), cancelada=True)),
]


async def main() -> None:
    # El diagrama sale de los tipos de retorno, no de una lista que mantengas.
    print(graph.render())

    print()
    for nombre, monto, estado in CASOS:
        salida = await graph.run(inputs=monto, state=estado)
        print(f"  {nombre:<16} pidió {monto:>6} → {salida}")


if __name__ == "__main__":
    asyncio.run(main())
