"""Qué declara cada modelo, y qué pasa cuando uno se cae.

    uv run python -m app.providers            # perfiles, sin llamar a la API
    uv run python -m app.providers --fallback # un run real con FallbackModel

El perfil es lo que Pydantic AI sabe del modelo ANTES de hablarle: ventana de
contexto, si soporta tools, qué modo de salida estructurada usa. De ahí salen
las decisiones que el framework toma por vos.
"""

import argparse
import asyncio

from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.providers.anthropic import AnthropicProvider

from app.agent.deps import Deps
from app.agent.triage import triage_agent
from app.core.db import SessionFactory, engine

# Las que deciden si tu agente puede existir sobre ese modelo.
CLAVES = [
    "context_window",
    "supports_tools",
    "supports_json_schema_output",
    "default_structured_output_mode",
    "supports_thinking",
]

MODELOS = ["claude-haiku-4-5", "claude-sonnet-4-5", "claude-opus-4-1"]


def _modelo(nombre: str) -> AnthropicModel:
    """Construir un modelo no habla con nadie: la key sólo hace falta al llamar.

    Provider explícito en vez del string "anthropic:…": es la forma que vas a
    necesitar cuando haya dos providers configurados a la vez.
    """
    return AnthropicModel(nombre, provider=AnthropicProvider())


def perfiles() -> None:
    perfiles = {n: _modelo(n).profile for n in MODELOS}

    ancho = max(len(n) for n in MODELOS) + 2
    print(f"\n{'':<34}" + "".join(f"{n:<{ancho}}" for n in MODELOS))
    for clave in CLAVES:
        fila = "".join(f"{str(perfiles[n].get(clave)):<{ancho}}" for n in MODELOS)
        print(f"{clave:<34}{fila}")

    print(f"\n{len(perfiles[MODELOS[0]])} flags en total por modelo.")


async def fallback() -> None:
    # Un id que no existe: la API devuelve 404, que es un ModelAPIError, que es
    # lo que FallbackModel intercepta por default.
    roto = _modelo("claude-inexistente-9")
    sano = _modelo("claude-haiku-4-5")

    model = FallbackModel(roto, sano)

    deps = Deps(session_factory=SessionFactory, customer_id="cus_ana")
    with triage_agent.override(model=model):
        result = await triage_agent.run("¿llegó mi pedido?", deps=deps)

    # Quién contestó realmente. El agente no se enteró del cambio.
    print(f"\nrespondió   {result.response.model_name}")
    print(f"categoría   {result.output.category}")

    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Perfiles y fallback de modelos.")
    parser.add_argument("--fallback", action="store_true", help="Hace un run real.")
    args = parser.parse_args()

    if args.fallback:
        asyncio.run(fallback())
    else:
        perfiles()


if __name__ == "__main__":
    main()
