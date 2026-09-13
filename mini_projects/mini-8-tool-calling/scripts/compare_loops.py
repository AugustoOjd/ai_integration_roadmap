"""Fase 8 — Los tres niveles, sobre el mismo prompt.

    uv run python -m scripts.compare_loops
    uv run python -m scripts.compare_loops "tu prompt acá"
    uv run python -m scripts.compare_loops "tu prompt" --degradado

El ejercicio que vale no es ver que los tres dan la misma respuesta (la dan).
Es el flag `--degradado`: rompe la descripción de `calculate` igual que en la
Fase 1 y te deja ver EN CUÁL DE LOS TRES te das cuenta más rápido de qué pasó.

Esa es la métrica real de una abstracción: no cuánto código te ahorra cuando
funciona, sino cuánto te cuesta entenderla cuando no.
"""

import asyncio
import logging
import sys
import time

from app.agent import run_agent
from app.agent_pydantic_ai import run_agent_with_pydantic_ai
from app.agent_runner import run_agent_with_runner
from app.tools.registry import registry

DEFAULT_PROMPT = "¿Qué hora es en Tokio? Y aparte, cuánto es 4823 por 1917."


def degradar_calculate() -> None:
    """Reemplaza la descripción de `calculate` por una inútil.

    Toca el registry en caliente para afectar SÓLO al nivel 1. Los niveles 2 y 3
    tienen sus propias copias de las tools (con docstrings propios), así que
    mantienen la descripción buena — lo cual, casualmente, ilustra otro costo de
    las abstracciones: la misma tool termina descrita en tres lugares.
    """
    tool = registry._tools["calculate"]  # noqa: SLF001 — es un script de estudio
    registry._tools["calculate"] = type(tool)(  # noqa: SLF001
        name=tool.name,
        description="hace cálculos",
        input_model=tool.input_model,
        func=tool.func,
    )


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    prompt = args[0] if args else DEFAULT_PROMPT

    if "--degradado" in sys.argv:
        degradar_calculate()
        print("!! descripción de `calculate` degradada a 'hace cálculos'\n")

    print(f"prompt: {prompt}")

    # ------------------------------------------------------------- nivel 1
    print(f"\n{'=' * 70}\n1. TU LOOP (app/agent.py)\n{'=' * 70}")
    started = time.perf_counter()
    result = await run_agent(prompt)
    print(f"\nrespuesta  : {result.text}")
    # Estos tres campos son lo que los otros dos niveles no te dan de arriba.
    print(f"tools_used : {result.tools_used}")
    print(f"iterations : {result.iterations}")
    print(f"tokens     : in={result.input_tokens} out={result.output_tokens}")
    print(f"tiempo     : {time.perf_counter() - started:.1f}s")

    # ------------------------------------------------------------- nivel 2
    print(f"\n{'=' * 70}\n2. TOOL_RUNNER DEL SDK (app/agent_runner.py)\n{'=' * 70}")
    started = time.perf_counter()
    # Es SÍNCRONO y estamos en una corrutina: llamarlo directo bloquearía el
    # event loop. `to_thread` es el mismo puente que usa el agente para las
    # tools — el problema no era de las tools, era de mezclar sync con async.
    texto = await asyncio.to_thread(run_agent_with_runner, prompt)
    print(f"respuesta  : {texto}")
    print("tools_used : (no expuesto de arriba)")
    print(f"tiempo     : {time.perf_counter() - started:.1f}s")

    # ------------------------------------------------------------- nivel 3
    print(f"\n{'=' * 70}\n3. PYDANTIC AI (app/agent_pydantic_ai.py)\n{'=' * 70}")
    started = time.perf_counter()
    answer = await run_agent_with_pydantic_ai(prompt)
    print(f"respuesta  : {answer.text}")
    # Esto es lo que NO tienen los otros dos: la salida llega tipada y
    # validada, no como texto libre que hay que parsear.
    print(f"confidence : {answer.confidence}   <- salida tipada y validada")
    print(f"tiempo     : {time.perf_counter() - started:.1f}s")


if __name__ == "__main__":
    asyncio.run(main())
