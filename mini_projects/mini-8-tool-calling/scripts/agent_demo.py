"""Fase 3 — Correr el agente desde la consola.

    uv run python -m scripts.agent_demo
    uv run python -m scripts.agent_demo "tu prompt acá"
    uv run python -m scripts.agent_demo "tu prompt" 1     # con max_iterations=1
"""

import asyncio
import logging
import sys

from app.agent import MaxIterationsError, run_agent

# Un prompt que necesita DOS tools encadenadas: primero la hora, y recién
# cuando la tenga puede armar la cuenta. Por eso no se resuelve en una vuelta:
# el modelo no puede pedir `calculate` hasta ver el minuto.
#
# Esperado: iterations >= 3 (pedir hora -> pedir cuenta -> redactar).
DEFAULT_PROMPT = "¿Qué hora es? Y decime cuánto da el minuto actual multiplicado por 2."


async def main() -> None:
    # El loop loguea cada vuelta con logger.info. Sin esta línea no se ve nada:
    # el nivel por default de Python es WARNING.
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    prompt = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PROMPT
    max_iterations = int(sys.argv[2]) if len(sys.argv) > 2 else 5

    print(f"prompt: {prompt}\n")
    try:
        result = await run_agent(prompt, max_iterations=max_iterations)
    except MaxIterationsError as exc:
        # Cortar limpio con un error explícito es el comportamiento correcto:
        # probá con max_iterations=1 sobre el prompt por default y mirá que
        # falla en vez de colgarse o de inventar una respuesta.
        print(f"\nNO CONVERGIÓ: {exc}")
        return

    print(f"\nrespuesta   : {result.text}")
    print(f"iterations  : {result.iterations}")
    print(f"tools_used  : {result.tools_used}")
    # El input acumulado es bastante mayor que el prompt porque cada vuelta
    # reenvía el historial entero más las definiciones de las tools.
    print(f"tokens      : in={result.input_tokens} out={result.output_tokens}")


if __name__ == "__main__":
    # `asyncio.run` arranca un event loop, corre la corrutina y lo cierra.
    # Es el único puente entre el mundo sync (este `if`) y el async (el agente).
    asyncio.run(main())
