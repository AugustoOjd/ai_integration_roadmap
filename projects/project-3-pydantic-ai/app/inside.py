"""El run, nodo por nodo.

    uv run python -m app.inside "el monitor llegó roto, devolvéme la plata"

`agent.run()` es azúcar sobre esto: por dentro un Agent es un pydantic-graph, y
`iter()` te deja avanzarlo a mano. Los nodos son el while-loop que escribiste a
mano, reificados.
"""

import argparse
import asyncio

from pydantic_ai import CallToolsNode, ModelRequestNode, UserPromptNode
from pydantic_graph import End

from app.agent.deps import Deps
from app.agent.triage import triage_agent
from app.core.db import SessionFactory, engine


def _describir(nodo: object) -> str:
    match nodo:
        case UserPromptNode():
            return "UserPromptNode    el prompt entra al grafo"
        case ModelRequestNode():
            return "ModelRequestNode  una llamada al modelo"
        case CallToolsNode():
            # Acá se decide si el grafo vuelve a ModelRequestNode o termina.
            partes = [p.part_kind for p in nodo.model_response.parts]
            return f"CallToolsNode     procesa la respuesta: {', '.join(partes)}"
        case End():
            return "End               el grafo terminó"
        case _:
            return type(nodo).__name__


async def main() -> None:
    parser = argparse.ArgumentParser(description="Recorre el grafo de un run.")
    parser.add_argument("mensaje")
    parser.add_argument("--customer", default="cus_bruno")
    parser.add_argument("--role", default="agent", choices=["customer", "agent"])
    args = parser.parse_args()

    deps = Deps(
        session_factory=SessionFactory, customer_id=args.customer, role=args.role
    )

    # iter() devuelve un AgentRun, que es iterable: cada vuelta es un nodo ya
    # ejecutado. Se puede además llamar a run.next(nodo) para avanzar de a uno.
    async with triage_agent.iter(args.mensaje, deps=deps) as run:
        paso = 0
        async for nodo in run:
            paso += 1
            print(f"{paso:>2}  {_describir(nodo)}")

        # El resultado del grafo, disponible recién cuando terminó.
        print(f"\noutput  {type(run.result.output).__name__}")
        print(f"usage   {run.usage.requests} requests, {run.usage.tool_calls} tools")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
