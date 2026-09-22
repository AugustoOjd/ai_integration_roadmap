"""El mismo agente, tres superficies.

    uv run python -m app.interfaces cli      # chat en la terminal
    uv run python -m app.interfaces web      # chat en el browser
    uv run python -m app.interfaces stream   # los eventos de un run, en vivo

Ninguna toca el agente: `triage_agent` es el mismo objeto de siempre. Lo que
cambia es quién lo maneja.
"""

import argparse
import asyncio

import uvicorn

from app.agent.deps import Deps
from app.agent.triage import triage_agent
from app.core.db import SessionFactory


def _deps() -> Deps:
    return Deps(session_factory=SessionFactory, customer_id="cus_ana", role="agent")


def cli() -> None:
    """REPL con historial: cada mensaje continúa la conversación anterior."""
    triage_agent.to_cli_sync(deps=_deps(), prog_name="triage")


def web() -> None:
    """Devuelve una app Starlette lista para servir."""
    uvicorn.run(triage_agent.to_web(deps=_deps()), host="127.0.0.1", port=8000)


async def stream() -> None:
    """Los eventos del run a medida que pasan, sin esperar al final.

    Es la base de cualquier UI propia: AG-UI y Vercel AI son este mismo flujo
    traducido a sus protocolos.
    """
    async with triage_agent.run_stream_events(
        "el monitor llegó roto, devolvéme la plata", deps=_deps()
    ) as eventos:
        async for evento in eventos:
            print(f"  {type(evento).__name__}")


def main() -> None:
    parser = argparse.ArgumentParser(description="El agente en distintas superficies.")
    parser.add_argument("modo", choices=["cli", "web", "stream"])
    args = parser.parse_args()

    match args.modo:
        case "cli":
            cli()
        case "web":
            print("http://127.0.0.1:8000")
            web()
        case "stream":
            asyncio.run(stream())


if __name__ == "__main__":
    main()
