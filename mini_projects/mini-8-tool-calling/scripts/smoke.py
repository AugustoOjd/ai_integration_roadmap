"""Primera llamada al modelo, sin tools.

El objetivo de este script NO es "ver si la API key anda". Es mirar la forma
CRUDA de una respuesta de la Messages API antes de que empecemos a taparla con
abstracciones. Todo el mini 8 se juega en leer bien tres campos:

    response.content      la lista de bloques (NO es un string)
    response.stop_reason  por qué paró: es quien maneja el control de flujo
    response.usage        qué gastaste

Se corre así:

    uv run python -m scripts.smoke
    uv run python -m scripts.smoke "tu prompt acá"
"""

import sys

from app.config import settings
from app.llm import get_client

DEFAULT_PROMPT = "Decime en una frase qué es una API."


def main() -> None:
    # sys.argv[0] es el nombre del script; de 1 en adelante son los argumentos.
    prompt = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PROMPT

    client = get_client()

    response = client.messages.create(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=settings.ANTHROPIC_MAX_TOKENS,
        # El historial completo de la conversación. Fijate que es una LISTA
        # aunque acá tenga un solo elemento: la API no tiene memoria ni sesión.
        # Cada request lleva TODO lo que pasó antes, y por eso en la Fase 3 el
        # costo de un loop de tools crece con cada vuelta: se reenvía todo.
        messages=[{"role": "user", "content": prompt}],
    )

    print(f"prompt      : {prompt}\n")

    # ------------------------------------------------------------------ 1/3
    # `content` es una LISTA de bloques, no un string. Con este request simple
    # viene un solo bloque de tipo "text", pero la misma lista puede traer
    # bloques "thinking" y, desde la Fase 1, bloques "tool_use".
    #
    # Por eso nunca se hace `response.content[0].text`: es una suposición sobre
    # qué vino primero, y en cuanto aparezca un bloque de otro tipo revienta.
    # Se itera y se mira `.type`.
    print(f"content     : {len(response.content)} bloque(s)")
    for i, block in enumerate(response.content):
        print(f"  [{i}] type={block.type!r}")
        if block.type == "text":
            print(f"      {block.text}")

    # ------------------------------------------------------------------ 2/3
    # `stop_reason` es POR QUÉ el modelo dejó de generar. Es el campo más
    # importante de todo el mini, porque a partir de la Fase 3 es literalmente
    # la condición del `while` del agente:
    #
    #   end_turn    terminó, hay respuesta final       (lo que vas a ver acá)
    #   tool_use    quiere que ejecutes algo           (Fase 1 en adelante)
    #   max_tokens  se cortó a la mitad, subí el techo
    #   refusal     los clasificadores de seguridad declinaron
    print(f"\nstop_reason : {response.stop_reason!r}")

    # ------------------------------------------------------------------ 3/3
    # Lo que gastaste, medido por el servidor. `input_tokens` es todo lo que le
    # mandaste (system + tools + historial entero); `output_tokens` es lo que
    # generó. Mirá cómo cambia esta cuenta en la Fase 3: el input crece vuelta a
    # vuelta porque el historial se reenvía completo.
    print(f"usage       : in={response.usage.input_tokens} out={response.usage.output_tokens}")

    # El objeto entero, por si querés ver los campos que no imprimimos (`id`,
    # `model`, `role`). Los objetos del SDK son modelos de Pydantic, así que
    # `.model_dump_json()` funciona sobre cualquiera de ellos.
    print(f"\n--- objeto completo ---\n{response.model_dump_json(indent=2)}")


if __name__ == "__main__":
    main()
