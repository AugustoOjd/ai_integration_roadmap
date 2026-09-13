"""Fase 6 — Qué hace el agente cuando una tool se rompe.

Registra dos tools que fallan a propósito y deja que el modelo las choque. Es
la prueba de que un fallo de tool NO es un fallo de la conversación: el error
vuelve al modelo como un `tool_result` marcado, y él reacciona.

De paso verifica algo de la Fase 4: acá se agregan dos tools nuevas al sistema
sin tocar una sola línea del loop. Si hubiera que tocarlo, el registry estaría
mal acoplado.

    uv run python -m scripts.failing_tool
"""

import asyncio
import logging
from typing import Annotated

from pydantic import Field

from app.agent import run_agent
from app.tools.registry import registry


@registry.tool
def get_stock_price(
    ticker: Annotated[str, Field(description="El símbolo. Ejemplo: 'AAPL'.")],
) -> float:
    """Devuelve el precio actual de una acción en dólares.

    Usala cuando te pregunten por el valor de una acción.
    """
    # Un fallo INESPERADO: el bug que no viste venir, el servicio caído, el
    # timeout. Sube como una excepción cualquiera, y el agente la atrapa en su
    # `except Exception`.
    #
    # Fijate qué NO va a ver el modelo: ni este mensaje, ni el nombre de la
    # excepción, ni el traceback. Todo eso se queda en el log del servidor.
    # Podría contener rutas, queries o credenciales, y lo que entra en un
    # `tool_result` el modelo lo puede repetir en su respuesta al usuario.
    raise ConnectionError(
        "conexión rechazada a market-data.internal:5432 "
        "(user=quant password=hunter2)"
    )


@registry.tool
def convert_currency(
    amount: Annotated[float, Field(description="El monto a convertir.")],
    currency: Annotated[str, Field(description="Moneda destino, ISO 4217: 'EUR', 'ARS'.")],
) -> str:
    """Convierte un monto en dólares a otra moneda.

    Usala para convertir valores entre monedas.
    """
    # Un fallo ESPERABLE y bien contado: la tool funciona, pero no para esta
    # entrada. El mensaje está escrito PARA EL MODELO —dice qué pasó, qué se
    # soporta, y da ejemplos— así que puede corregirse solo en la vuelta
    # siguiente en vez de rendirse.
    #
    # Sube como ValueError, no como ToolError, y aun así el agente lo trata
    # como inesperado... lo cual es exactamente lo que queremos observar en la
    # prueba: el texto que ve el modelo NO es este.
    supported = ("EUR", "BRL", "ARS")
    if currency.upper() not in supported:
        raise ValueError(f"moneda no soportada: {currency!r}. Disponibles: {supported}")
    return f"{amount} USD = ??? {currency.upper()}"


PRUEBAS = [
    # 1. Tool que explota por un error interno. Esperado: el modelo NO ve el
    #    connection string, recibe el mensaje genérico, y le avisa al usuario
    #    que no pudo obtener el dato en vez de inventar un precio.
    "¿Cuánto vale la acción de Apple?",
    # 2. Tool alucinada: `send_email` no existe. Esperado: UnknownToolError, el
    #    modelo lee la lista de tools disponibles en el mensaje de error y
    #    reacciona.
    "Mandale un mail a juan@example.com diciéndole que llego tarde.",
    # 3. Argumentos inválidos: 'expression' es requerido y el tipo importa.
    #    Esperado: el modelo se corrige solo en la vuelta siguiente.
    "Convertí 100 dólares a yenes japoneses.",
    # 4. El caso sano, para contrastar: dos tools independientes en UNA sola
    #    vuelta. Mirá el log: dos líneas '->' bajo la misma iteración.
    "¿Qué hora es en Tokio? Y aparte, cuánto es 4823 por 1917.",
]


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    for prompt in PRUEBAS:
        print(f"\n{'=' * 70}\n{prompt}\n{'=' * 70}")
        try:
            result = await run_agent(prompt)
        except Exception as exc:
            # Si algo llega hasta acá, el agente NO está conteniendo los fallos
            # de tools y la Fase 6 no está haciendo su trabajo.
            print(f"LA CORRIDA MURIÓ: {type(exc).__name__}: {exc}")
            continue

        print(f"\nrespuesta : {result.text}")
        print(f"tools     : {result.tools_used}  |  iteraciones: {result.iterations}")


if __name__ == "__main__":
    asyncio.run(main())
