"""Fase 1 — Anatomía de una tool: qué le mandás al modelo y qué te devuelve.

Acá NO se ejecuta ninguna tool. El objetivo es ver las dos mitades del
protocolo por separado, antes de cerrar el círculo en la Fase 2:

    lo que mandás   ->  una tool: name + description + input_schema (JSON, no código)
    lo que volvés   ->  un bloque `tool_use`: id + name + input

Y, sobre todo, ver DÓNDE vive la decisión de usar una tool: no en tu código,
sino en el modelo, guiado por lo único que ve de tu tool — su descripción.

    uv run python -m scripts.tool_anatomy
"""

from anthropic.types import Message, ToolParam

from app.config import settings
from app.llm import get_client

# ---------------------------------------------------------------------------
# La tool, escrita a mano
# ---------------------------------------------------------------------------
# Tres campos, y ninguno de los tres es código. El modelo NUNCA ve tu función
# Python: ve este JSON, el mensaje del usuario, y con eso decide.
#
#   name          el identificador. Es lo que te va a devolver para que sepas
#                 qué ejecutar. snake_case, estable: si lo cambiás, cambiás el
#                 contrato.
#
#   description   PROMPT. Esta es la pieza de ingeniería más importante de una
#                 tool y la que casi nadie trata con el cuidado que mereceria.
#                 Una buena descripción dice CUÁNDO usarla, qué espera en cada
#                 campo, y cuáles son sus LÍMITES. El experimento de abajo
#                 muestra qué pasa cuando no lo hace.
#
#   input_schema  JSON Schema de los argumentos. Es el contrato de entrada: le
#                 dice al modelo qué forma tienen que tener los datos. Fijate
#                 que cada propiedad tiene SU PROPIA `description`; el modelo
#                 las lee, y son el lugar donde van los ejemplos de formato.
CALCULATE_TOOL: ToolParam = {
    "name": "calculate",
    "description": (
        "Evalúa una expresión aritmética y devuelve el resultado numérico. "
        "Usala siempre que necesites hacer una cuenta, por simple que parezca: "
        "es exacta, mientras que calcular de memoria es propenso a errores. "
        "Soporta únicamente aritmética: los operadores + - * / // % ** y "
        "paréntesis. No resuelve ecuaciones, ni álgebra simbólica, ni "
        "conversiones de unidades."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": (
                    "La expresión a evaluar, en sintaxis de Python. "
                    "Ejemplos: '42 * 2', '(15 + 5) / 4', '2 ** 10'."
                ),
            }
        },
        # Sin esto, el modelo puede mandarte `{}` y tu función explota con un
        # TypeError por argumento faltante.
        "required": ["expression"],
    },
}

# La MISMA tool —mismo nombre, mismo schema, misma capacidad— con una
# descripción pobre. Es la única variable del experimento 3.
VAGUE_TOOL: ToolParam = {
    **CALCULATE_TOOL,
    "description": "hace cálculos",
}

MATH_PROMPT = "¿Cuánto es 4823 por 1917?"


def ask(prompt: str, **kwargs) -> Message:
    """Una llamada al modelo. `kwargs` deja pasar `tools`, `tool_choice`, etc."""
    return get_client().messages.create(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=settings.ANTHROPIC_MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
        **kwargs,
    )


def report(title: str, response: Message) -> None:
    """Imprime los bloques de una respuesta, distinguiendo por `.type`.

    Acá se ve por qué en la Fase 0 insistimos con que `content` es una lista:
    ahora la misma lista puede traer bloques de dos tipos distintos, y a veces
    trae los dos (el modelo puede decir "voy a calcular eso" ANTES del bloque
    `tool_use`).
    """
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")
    print(f"stop_reason: {response.stop_reason!r}")

    for block in response.content:
        if block.type == "text":
            print(f"  [text]     {block.text.strip()}")
        elif block.type == "tool_use":
            # Estos tres campos son todo el "pedido" del modelo.
            #
            # `id` es lo más importante y lo que menos parece: es la clave de
            # correlación. En la Fase 2 tu respuesta tiene que citar este id
            # exacto para que la API sepa a qué pedido le estás contestando.
            # Con varias tools en paralelo (Fase 6) es lo único que las
            # distingue.
            print(f"  [tool_use] id={block.id}")
            print(f"             name={block.name!r}")
            print(f"             input={block.input!r}")


def main() -> None:
    # -------------------------------------------------------- Experimento 1
    # Sin tools. El modelo no tiene más opción que calcular de memoria, y un
    # LLM multiplicando números de cuatro cifras es exactamente tan confiable
    # como vos haciéndolo mentalmente y rápido.
    #
    # (La respuesta correcta es 9.245.691. Comparala con lo que salga.)
    report("1. SIN tools — el modelo calcula de memoria", ask(MATH_PROMPT))

    # -------------------------------------------------------- Experimento 2
    # La misma pregunta, ahora con la tool declarada. Cambia UNA cosa en el
    # request y cambia todo en la respuesta: `stop_reason` pasa de 'end_turn' a
    # 'tool_use' y aparece un bloque con el pedido.
    #
    # Fijate que el modelo NO calculó nada: te delegó la cuenta a vos. Está
    # esperando. Esa conversación quedó a mitad de camino — cerrarla es la
    # Fase 2.
    report(
        "2. CON tools — el modelo delega",
        ask(MATH_PROMPT, tools=[CALCULATE_TOOL]),
    )

    # -------------------------------------------------------- Experimento 3
    # El experimento que justifica toda la fase. La tool es idéntica en
    # nombre, schema y capacidad: lo único que cambió es la descripción.
    #
    # Con "hace cálculos" el modelo pierde la razón para preferirla ("¿para qué
    # la voy a llamar, si esto lo sé hacer?") y es bastante probable que vuelva
    # a contestar de memoria. Puede que a veces la llame igual — los modelos no
    # son determinísticos — y eso también es parte de la lección: una
    # descripción pobre no rompe, DEGRADA, que es mucho peor de debuggear.
    #
    # Esta es la razón por la que, cuando una tool "no se llama nunca", el bug
    # está en la descripción y no en el código, nueve de cada diez veces.
    report(
        "3. Misma tool, descripción pobre ('hace cálculos')",
        ask(MATH_PROMPT, tools=[VAGUE_TOOL]),
    )

    # -------------------------------------------------------- Experimento 4
    # `tool_choice` es la perilla que controla cuánta libertad tiene el modelo:
    #
    #   auto (default)          decide él. Es lo que querés casi siempre.
    #   none                    tiene las tools a la vista pero no puede usarlas.
    #   {"type": "any"}         DEBE llamar a alguna, él elige cuál.
    #   {"type": "tool", ...}   DEBE llamar a esa. Sin salida.
    #
    # `auto` es el default porque el punto de tener tools es que el modelo
    # evalúe si hacen falta. Forzar sirve para casos acotados (estructurar una
    # salida, un paso obligatorio de un pipeline), pero acá lo usamos al revés,
    # para mostrar el costo: le preguntamos algo que no tiene nada que ver con
    # matemática y lo obligamos a llamar a `calculate`.
    #
    # El modelo obedece e inventa una expresión. Es basura, y es la lección:
    # forzar una tool no hace que la situación la amerite. Un modelo forzado
    # alucina argumentos con tal de cumplir.
    report(
        "4. tool_choice forzado sobre una pregunta que no es de matemática",
        ask(
            "¿Cuál es la capital de Francia?",
            tools=[CALCULATE_TOOL],
            tool_choice={"type": "tool", "name": "calculate"},
        ),
    )

    print(
        "\n"
        + "=" * 70
        + "\nNingún bloque `tool_use` de arriba se ejecutó: sólo los miramos.\n"
        "Las cuatro conversaciones quedaron abiertas, con el modelo esperando\n"
        "un resultado que nunca le mandamos. Cerrar ese círculo es la Fase 2.\n"
        + "=" * 70
    )


if __name__ == "__main__":
    main()
