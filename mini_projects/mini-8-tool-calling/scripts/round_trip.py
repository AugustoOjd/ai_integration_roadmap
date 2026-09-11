"""Fase 2 — Cerrar el círculo: ejecutar la tool y devolver el resultado.

La Fase 1 dejó la conversación a mitad de camino: el modelo pidió algo y nunca
le contestamos. Acá la cerramos, a mano, en un solo round-trip.

El historial termina con TRES mensajes, no dos:

    user      "¿cuánto es 4823 por 1917?"
    assistant [text?, tool_use(id=X)]        <- la respuesta COMPLETA del modelo
    user      [tool_result(tool_use_id=X)]   <- tu respuesta, con rol `user`

    uv run python -m scripts.round_trip
"""

import json
import operator
import re

from anthropic import BadRequestError
from anthropic.types import MessageParam

from app.config import settings
from app.llm import get_client
from scripts.tool_anatomy import CALCULATE_TOOL, MATH_PROMPT

# ---------------------------------------------------------------------------
# La implementación (de juguete, a propósito)
# ---------------------------------------------------------------------------
# Esto resuelve UNA operación entre dos números y nada más. Es deliberadamente
# pobre: en esta fase lo que se aprende es el PROTOCOLO, no el evaluador.
#
# La versión de verdad —y por qué el `eval(expression)` que propone el README
# del mini es ejecución remota de código— es la Fase 5.
_BINARY_OP = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*([-+*/])\s*(-?\d+(?:\.\d+)?)\s*$")
_OPS = {"+": operator.add, "-": operator.sub, "*": operator.mul, "/": operator.truediv}


def calculate(expression: str) -> float:
    match = _BINARY_OP.match(expression)
    if match is None:
        raise ValueError(f"expresión no soportada por esta versión: {expression!r}")
    left, op, right = match.groups()
    return _OPS[op](float(left), float(right))


def execute(name: str, tool_input: dict) -> str:
    """Despacha por nombre. Sí, un `if`.

    En la Fase 4 esto se convierte en un registry, porque con tres tools ya son
    tres lugares para desincronizar (el schema, la función y este `if`). Por
    ahora el `if` es honesto y deja ver que no hay nada mágico: el modelo te
    manda un string con un nombre y vos elegís qué correr.

    Devuelve un string porque eso es lo que espera el bloque `tool_result`. Lo
    que sea que devuelvas acá entra al contexto del modelo (y lo pagás en
    tokens), así que el formato importa.
    """
    if name == "calculate":
        # `**tool_input` desempaqueta el dict a argumentos con nombre. Funciona
        # porque las claves del schema y los parámetros de la función coinciden
        # — una coincidencia que hoy sostenés vos a mano, y que el registry de
        # la Fase 4 pasa a garantizar.
        return str(calculate(**tool_input))
    raise ValueError(f"tool desconocida: {name!r}")


def dump(label: str, messages: list[MessageParam]) -> None:
    """Imprime el historial completo. Mirar esto es la fase."""
    print(f"\n{'=' * 70}\n{label}  ({len(messages)} mensajes)\n{'=' * 70}")
    for i, message in enumerate(messages):
        content = message["content"]
        if isinstance(content, str):
            print(f"[{i}] {message['role']:9} {content!r}")
            continue
        # Cuando el contenido es una lista de bloques, los bloques del assistant
        # son objetos del SDK y los que armás vos son dicts. Los normalizamos a
        # dict sólo para imprimir.
        blocks = [b if isinstance(b, dict) else b.model_dump() for b in content]
        print(f"[{i}] {message['role']:9} {len(blocks)} bloque(s)")
        for block in blocks:
            print(f"      {json.dumps(block, ensure_ascii=False, default=str)}")


def main() -> None:
    client = get_client()

    # ------------------------------------------------------------- turno 1
    # El historial arranca con el mensaje del usuario. A partir de acá, este
    # `messages` es EL estado de la conversación: la API no guarda nada, cada
    # request lleva todo.
    messages: list[MessageParam] = [{"role": "user", "content": MATH_PROMPT}]

    first = client.messages.create(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=settings.ANTHROPIC_MAX_TOKENS,
        messages=messages,
        tools=[CALCULATE_TOOL],
    )
    print(f"stop_reason del primer turno: {first.stop_reason!r}")

    # ---------------------------------------------- REGLA 1: reenviar TODO
    # El mensaje del assistant que agregás al historial es `first.content`
    # ENTERO y sin tocar.
    #
    # El error clásico es guardar sólo el texto (`first.content[0].text`) y
    # perder el bloque `tool_use`. Si hacés eso, el pedido del modelo
    # desaparece del historial, y tu `tool_result` del turno siguiente pasa a
    # ser una respuesta a una pregunta que nadie hizo: la API lo rechaza.
    #
    # Con Haiku y thinking apagado acá vas a ver sólo `text` y `tool_use`, pero
    # la regla es "reenviar la lista completa", no "reenviar text y tool_use".
    messages.append({"role": "assistant", "content": first.content})

    # -------------------------------------- REGLA 2: un result por cada use
    # Recorremos los bloques buscando pedidos. Para cada `tool_use` ejecutamos
    # y armamos su `tool_result`.
    results = []
    for block in first.content:
        if block.type != "tool_use":
            continue

        output = execute(block.name, dict(block.input))
        print(f"ejecutado: {block.name}({block.input}) -> {output}")

        results.append(
            {
                "type": "tool_result",
                # El id EXACTO que vino en el `tool_use`. No es decorativo: es
                # lo único que le dice a la API a qué pedido estás contestando.
                "tool_use_id": block.id,
                "content": output,
            }
        )

    # ---------------------------------------- REGLA 3: el result va como USER
    # Contraintuitivo la primera vez: vos sos el "usuario" desde la perspectiva
    # del modelo. Los roles de la API no son "humano" y "máquina", son "quien
    # provee contexto" y "quien genera". El resultado de una tool es contexto
    # que vos le estás dando, así que va con rol `user`.
    messages.append({"role": "user", "content": results})

    dump("HISTORIAL antes de la segunda llamada", messages)

    # ------------------------------------------------------------- turno 2
    # Exactamente la misma llamada, con el historial más largo. Ahora el modelo
    # tiene el resultado y puede redactar la respuesta final: `stop_reason`
    # vuelve como 'end_turn'.
    #
    # `tools` se sigue mandando aunque ya no lo "necesite". Las tools no son
    # estado de la conversación, son parte de cada request: si las sacás, el
    # modelo deja de poder pedir nada de acá en adelante.
    second = client.messages.create(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=settings.ANTHROPIC_MAX_TOKENS,
        messages=messages,
        tools=[CALCULATE_TOOL],
    )
    print(f"\nstop_reason del segundo turno: {second.stop_reason!r}")
    for block in second.content:
        if block.type == "text":
            print(f"respuesta final: {block.text.strip()}")

    # ------------------------------------------------------- el error a propósito
    # Aprender el mensaje de error acá, provocándolo, vale más que evitarlo:
    # cuando te aparezca de verdad en la Fase 6 vas a saber qué mirar.
    #
    # Repetimos la segunda llamada con un `tool_use_id` inventado. El id no
    # corresponde a ningún `tool_use` del historial, así que quedan dos cosas
    # mal a la vez: hay un `tool_use` sin su result, y un result sin su `use`.
    print(f"\n{'=' * 70}\nEL MISMO REQUEST CON UN tool_use_id INVENTADO\n{'=' * 70}")
    broken = messages[:-1] + [
        {"role": "user", "content": [{**results[0], "tool_use_id": "toolu_no_existe"}]}
    ]
    try:
        client.messages.create(
            model=settings.ANTHROPIC_MODEL,
            max_tokens=settings.ANTHROPIC_MAX_TOKENS,
            messages=broken,
            tools=[CALCULATE_TOOL],
        )
    except BadRequestError as exc:
        # 400: el request está mal formado. No se reintenta, porque reintentarlo
        # da el mismo error. Esa distinción —error de cliente vs error
        # transitorio— es la que mapeamos a códigos HTTP en la Fase 7.
        print(f"BadRequestError (HTTP {exc.status_code}):\n  {exc.message}")


if __name__ == "__main__":
    main()
