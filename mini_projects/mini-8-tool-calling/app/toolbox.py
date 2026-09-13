"""Las tools disponibles — versión PROVISIONAL.

Este módulo existe para que la Fase 3 tenga con qué hacer el loop, y tiene a la
vista el problema que resuelve la Fase 4: la misma información está escrita en
tres lugares que nada mantiene sincronizados.

    1. el `input_schema` del dict      (lo que ve el modelo)
    2. la firma de la función Python   (lo que espera tu código)
    3. el `if` de `execute()`          (lo que conecta los dos)

Agregá un parámetro en 1 y olvidate de 2: explota en runtime con un TypeError,
en producción, cuando al modelo se le ocurra mandarlo. El registry de la Fase 4
hace que el schema se DERIVE de la función, y entonces hay una sola fuente de
verdad y el `if` desaparece.

Las implementaciones también son de juguete: las reales (y por qué `eval()` no)
son la Fase 5.
"""

import operator
import re
from datetime import datetime

from anthropic.types import ToolParam

# ---------------------------------------------------------------------------
# Definiciones: lo único que ve el modelo
# ---------------------------------------------------------------------------

CALCULATE_TOOL: ToolParam = {
    "name": "calculate",
    "description": (
        "Evalúa una expresión aritmética y devuelve el resultado numérico. "
        "Usala siempre que necesites hacer una cuenta, por simple que parezca: "
        "es exacta, mientras que calcular de memoria es propenso a errores. "
        "Soporta únicamente aritmética: los operadores + - * / y paréntesis. "
        "No resuelve ecuaciones ni conversiones de unidades."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": (
                    "La expresión a evaluar, en sintaxis de Python. "
                    "Ejemplos: '42 * 2', '(15 + 5) / 4'."
                ),
            }
        },
        "required": ["expression"],
    },
}

# Una tool SIN argumentos. Es un caso que conviene ver temprano porque rompe la
# intuición de "una tool es una función con parámetros": acá el `properties`
# está vacío y `required` no existe.
#
# Existe porque el modelo NO TIENE RELOJ. No es que sea impreciso con la hora:
# no tiene ninguna noción de "ahora". Su única fuente de la fecha sos vos, y si
# no se la das, inventa una o dice que no puede saberla.
GET_CURRENT_TIME_TOOL: ToolParam = {
    "name": "get_current_time",
    "description": (
        "Devuelve la fecha y hora actuales en formato ISO 8601 con zona "
        "horaria. Usala siempre que necesites saber qué día u hora es: no "
        "tenés forma de saberlo por tu cuenta."
    ),
    "input_schema": {"type": "object", "properties": {}},
}

# El orden de esta lista no le importa al modelo, pero sí a la caché de prompts:
# las tools se serializan antes que el system y los mensajes, así que una lista
# que cambia de orden entre requests invalida la caché entera. Manténela estable.
TOOLS: list[ToolParam] = [CALCULATE_TOOL, GET_CURRENT_TIME_TOOL]

# ---------------------------------------------------------------------------
# Implementaciones
# ---------------------------------------------------------------------------

_BINARY_OP = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*([-+*/])\s*(-?\d+(?:\.\d+)?)\s*$")
_OPS = {"+": operator.add, "-": operator.sub, "*": operator.mul, "/": operator.truediv}


def calculate(expression: str) -> float:
    """Una sola operación entre dos números. Versión de juguete (ver Fase 5)."""
    match = _BINARY_OP.match(expression)
    if match is None:
        raise ValueError(f"expresión no soportada: {expression!r}")
    left, op, right = match.groups()
    return _OPS[op](float(left), float(right))


def get_current_time() -> str:
    """La hora local, con offset de zona horaria explícito.

    `.astimezone()` sobre un datetime naive le pega la zona local, y por eso el
    ISO sale como '2026-09-12T14:30:00-03:00' y no como '2026-09-12T14:30:00'.
    Esa diferencia importa: un timestamp sin zona es ambiguo, y el modelo no
    tiene forma de desambiguarlo — va a asumir lo que se le ocurra.
    """
    return datetime.now().astimezone().isoformat(timespec="seconds")


def execute(name: str, tool_input: dict) -> str:
    """Despacha por nombre y devuelve un string (que es lo que espera tool_result).

    El `raise` del final no es paranoia: los modelos alucinan nombres de tools,
    sobre todo cuando hay varias con nombres parecidos. En la Fase 6 esto deja
    de ser una excepción que sube y pasa a ser un `tool_result` con
    `is_error: True` — decirle al modelo "esa tool no existe" hace que se
    corrija solo, mientras que reventar mata el request entero.
    """
    if name == "calculate":
        return str(calculate(**tool_input))
    if name == "get_current_time":
        return get_current_time()
    raise ValueError(f"tool desconocida: {name!r}")
