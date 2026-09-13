"""Nivel 3 — El mismo agente, con Pydantic AI.

Acá cambia el vocabulario. Ya no hablás de `tool_use`, `tool_result` ni
`stop_reason`: hablás de *agentes*, *tools* y *output tipado*. El protocolo de
Anthropic sigue existiendo abajo, pero no lo ves por ningún lado.

Lo que gana Pydantic AI sobre el `tool_runner`:

  - Es agnóstico del proveedor. `Agent("anthropic:...")` se cambia por
    `Agent("openai:...")` y el resto del archivo no se toca. Traduce a cada
    dialecto (`input_schema` vs `parameters`, `stop_reason` vs `finish_reason`,
    los `tool_result` en un mensaje vs en varios).
  - Valida la SALIDA del modelo contra un tipo, no sólo la entrada de las
    tools. Y si no valida, reintenta solo pasándole el error de validación.

Lo que pierde: visibilidad. Cuando una tool deja de llamarse, estás debuggeando
a través de una capa más.

Nota: Pydantic AI se mueve rápido y algunos nombres cambiaron entre versiones
(`result.data` pasó a `result.output`). Si algo no coincide, chequeá la versión
que resolvió `uv sync`. Que el protocolo crudo de la Fase 2 NO tenga ese
problema también es parte de la comparación.
"""

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider

from app.config import settings
from app.tools.calculator import calculate as _calculate
from app.tools.clock import get_current_time as _get_current_time
from app.tools.search import search as _search


class Answer(BaseModel):
    """La respuesta, como TIPO.

    Esto no existe en los otros dos niveles y es lo más interesante del
    framework. En tu loop y en el `tool_runner`, la salida es texto libre: si
    querés un número o una lista, parseás a mano y rezás.

    Acá el tipo es parte del contrato con el modelo: Pydantic AI lo convierte en
    un schema, se lo impone, valida lo que vuelve, y si no valida le devuelve el
    error de validación para que reintente. Es el mismo mecanismo del registry
    de la Fase 4, pero aplicado a la SALIDA en vez de a la entrada.
    """

    text: str = Field(description="La respuesta para el usuario, en una o dos frases.")
    confidence: float = Field(ge=0, le=1, description="Qué tan seguro estás, de 0 a 1.")


# La forma corta de elegir modelo es un string con el proveedor adelante:
#
#     Agent(f"anthropic:{settings.ANTHROPIC_MODEL}")
#
# y cambiar de proveedor es cambiar ese string. Pero esa forma resuelve la
# credencial leyendo ANTHROPIC_API_KEY del ENTORNO DEL PROCESO, y nuestra key
# no está ahí: vive en `.env`, que `pydantic-settings` lee hacia el objeto
# `settings` sin exportar nada a `os.environ`.
#
# Es una distinción que conviene tener clara porque pega en todos lados
# (Docker, CI, systemd):
#
#     .env                       un archivo que ALGUIEN tiene que leer
#     export ANTHROPIC_API_KEY=  el entorno real del proceso
#
# La salida fácil sería exportarla al entorno, pero entonces habría dos fuentes
# de verdad para la misma credencial. Preferimos la explícita: se la pasamos,
# igual que en `app/llm.py`.
_model = AnthropicModel(
    settings.ANTHROPIC_MODEL,
    provider=AnthropicProvider(api_key=settings.ANTHROPIC_API_KEY.get_secret_value()),
)

# Lo mismo con OpenAI, para ver hasta dónde llega la portabilidad. Cambian tres
# líneas —el import, la clase del modelo y la del provider— y NADA más:
#
#     from pydantic_ai.models.openai import OpenAIModel
#     from pydantic_ai.providers.openai import OpenAIProvider
#
#     _model = OpenAIModel(
#         "gpt-5",
#         provider=OpenAIProvider(api_key=settings.OPENAI_API_KEY.get_secret_value()),
#     )
#
# (Si la versión instalada no tiene `OpenAIModel`, buscá `OpenAIChatModel`: le
# cambiaron el nombre en algún release. Otra muestra de lo mismo que ya nos
# pasó con `result.data` -> `result.output`.)
#
# O en forma corta, si la key SÍ está en el entorno del proceso:
#
#     agent = Agent("openai:gpt-5", output_type=Answer, system_prompt=...)
#
# Lo importante es lo que NO se toca: los tres `@agent.tool_plain` de abajo, el
# `output_type=Answer`, el `system_prompt` y el `await agent.run(prompt)`.
# Pydantic AI traduce por dentro todo lo que en la Fase 2 viste a mano:
# `input_schema` pasa a `parameters`, `stop_reason` a `finish_reason`, y los
# `tool_result` que en Anthropic van juntos en un mensaje `user` pasan a ser un
# mensaje `tool` por cada tool.
#
# El caveat de siempre: el código es portable, el COMPORTAMIENTO no. Las
# descripciones de tus tools están afinadas para cómo decide este modelo; con
# otro, las mismas tools se llaman en momentos distintos.
agent = Agent(
    _model,
    output_type=Answer,
    system_prompt=(
        "Sos un asistente conciso. Usá las tools disponibles en vez de "
        "responder de memoria cuando la pregunta lo amerite."
    ),
)


# `tool_plain` es para tools que no necesitan contexto de la corrida. La otra
# variante, `@agent.tool`, recibe un `RunContext` como primer argumento, que es
# por donde Pydantic AI pasa DEPENDENCIAS —una conexión a la base, el usuario
# autenticado— sin variables globales.
#
# Esa es una pieza que en tu registry no existe y que en un agente real se
# vuelve necesaria rápido: una tool que consulta pedidos necesita saber DE QUIÉN
# son los pedidos, y esa información no puede venir del modelo.
@agent.tool_plain
def calculate(expression: str) -> float:
    """Evalúa una expresión aritmética y devuelve el resultado numérico.

    Soporta números, paréntesis y los operadores + - * / // % ** . No resuelve
    ecuaciones ni conversiones de unidades.
    """
    return _calculate(expression)


@agent.tool_plain
def get_current_time(timezone: str | None = None) -> str:
    """Devuelve la fecha y hora actuales en ISO 8601 con zona horaria.

    El parámetro `timezone` es una zona IANA, por ejemplo 'Asia/Tokyo'.
    """
    return _get_current_time(timezone)


@agent.tool_plain
def search(query: str) -> list[dict[str, str]]:
    """Busca información sobre un tema y devuelve fragmentos relevantes."""
    return _search(query)


async def run_agent_with_pydantic_ai(prompt: str) -> Answer:
    """La misma feature, en una línea.

    Y ahora la pregunta que vale la pena hacerse mirando este archivo:

        ¿dónde quedó el `tool_use_id`?

    Existe: Pydantic AI lo genera, lo correlaciona y lo manda. Pero no hay forma
    de verlo desde acá sin pedir el historial con `result.all_messages()`. En la
    Fase 2 ese id era lo primero que mirabas; acá es un detalle de
    implementación de otra gente.

    Eso no es malo por sí mismo —es el punto de una abstracción— pero es
    exactamente lo que te va a faltar el día que una tool deje de llamarse y no
    entiendas por qué.
    """
    result = await agent.run(prompt)
    return result.output
