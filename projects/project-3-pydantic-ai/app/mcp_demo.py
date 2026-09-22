"""Tools que no son funciones de tu proceso.

    uv run python -m app.mcp_demo "¿dónde está mi paquete?"

Levanta app/mcp_server.py como proceso aparte, se conecta por stdio y le suma
sus tools al agente. Para el modelo son tools como cualquier otra: el schema
llega igual, sólo que lo declaró otro programa.
"""

import argparse
import asyncio
from pathlib import Path

from pydantic_ai.mcp import MCPToolset

from app.agent.deps import Deps
from app.agent.triage import TOOLSET, triage_agent
from app.core.db import SessionFactory, engine

SERVER = Path(__file__).parent / "mcp_server.py"


async def main() -> None:
    parser = argparse.ArgumentParser(description="El agente con un server MCP.")
    parser.add_argument("mensaje")
    parser.add_argument("--customer", default="cus_ana")
    args = parser.parse_args()

    # El path del script: Pydantic AI lo envuelve en un cliente stdio y lo
    # arranca él. Con una URL sería exactamente la misma línea.
    envios = MCPToolset(str(SERVER))

    deps = Deps(session_factory=SessionFactory, customer_id=args.customer)

    # override(toolsets=…) REEMPLAZA la lista, así que el propio va también.
    # Para el modelo son todas tools iguales; que una viva en otro proceso no
    # aparece en el schema.
    with triage_agent.override(toolsets=[TOOLSET, envios]):
        result = await triage_agent.run(args.mensaje, deps=deps)

    print(f"\ncategoría   {result.output.category}")
    print(f"resumen     {result.output.summary}")
    print(f"\n{result.usage.tool_calls} tool calls")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
