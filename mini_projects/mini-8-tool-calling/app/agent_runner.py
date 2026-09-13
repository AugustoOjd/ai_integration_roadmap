"""Nivel 2 — El mismo agente, con el `tool_runner` del SDK.

Todo el loop de `app/agent.py` ya viene hecho en el SDK de Anthropic. Lo
escribimos a mano primero a propósito; esta es la comparación.

Lo que cambia: no armás el historial, no leés `stop_reason`, no recorrés los
bloques. Pasás las tools y pedís el resultado final.

Lo que NO cambia: seguís hablando el protocolo de Anthropic. Las tools siguen
siendo `tool_use` y `tool_result` por debajo, sólo que el SDK los maneja. Por
eso es un nivel intermedio y no un framework: te abstrae el LOOP, no el modelo.

Ojo: `tool_runner` está en `client.beta.messages`, o sea que es una API en beta
y puede cambiar de forma entre versiones del SDK. Ese es, en sí mismo, uno de
los datos de la comparación.
"""

import json
import logging

from anthropic import beta_tool

from app.config import settings
from app.llm import get_client
from app.tools.calculator import calculate as _calculate
from app.tools.clock import get_current_time as _get_current_time
from app.tools.search import search as _search

logger = logging.getLogger(__name__)


# El decorador del SDK hace lo mismo que tu registry de la Fase 4: deriva
# `name` del nombre de la función, `description` del docstring, e `input_schema`
# de los type hints.
#
# Que sean equivalentes no es casualidad — es la señal de que el registry que
# escribiste no era una invención tuya, sino el patrón estándar. La diferencia
# está en lo que pasa después: tu registry devuelve el schema y te deja
# ejecutar a vos; este ejecuta solo.
# Las tres devuelven `str`, y no es cosmético: el runner mete el valor de
# retorno CRUDO en el `tool_result`, y la API exige que ese contenido sea un
# string o una lista de bloques. Devolver un `float` o una `list[dict]` es un
# 400 en la cara:
#
#     tool_result.content: Found a number, but `tool_result` content must
#     either be a string or a list of content blocks.
#
# Tu registry de la Fase 4 hacía esta conversión por vos (`str` para escalares,
# JSON para estructuras). El runner te abstrae el loop, pero no eso — y es un
# buen recordatorio de que una abstracción te cubre lo que decidió cubrir, no
# todo lo que hacía tu código.


@beta_tool
def calculate(expression: str) -> str:
    """Evalúa una expresión aritmética y devuelve el resultado numérico.

    Soporta números, paréntesis y los operadores + - * / // % ** . No resuelve
    ecuaciones ni conversiones de unidades.

    Args:
        expression: La expresión a evaluar. Ejemplos: '42 * 2', '(15 + 5) / 4'.
    """
    # La implementación es la MISMA de la Fase 5, importada. Lo que cambia entre
    # los tres niveles es quién orquesta, nunca qué hacen las tools.
    return str(_calculate(expression))


@beta_tool
def get_current_time(timezone: str | None = None) -> str:
    """Devuelve la fecha y hora actuales en ISO 8601 con zona horaria.

    Args:
        timezone: Zona IANA, por ejemplo 'Asia/Tokyo'. Si se omite, la local.
    """
    return _get_current_time(timezone)


@beta_tool
def search(query: str) -> str:
    """Busca información sobre un tema y devuelve fragmentos relevantes.

    Args:
        query: Los términos a buscar.
    """
    # Una lista de dicts tampoco es contenido válido para un `tool_result`:
    # "lista de bloques" significa bloques del protocolo (`{"type": "text",
    # ...}`), no cualquier lista. Va como JSON, que el modelo lee sin problema.
    return json.dumps(_search(query), ensure_ascii=False)


TOOLS = [calculate, get_current_time, search]


def run_agent_with_runner(prompt: str) -> str:
    """La misma feature de `app.agent.run_agent`, en cinco líneas.

    Compará con las ~90 de `run_agent` y mirá qué desapareció:

        - el `for iteration in range(...)`      -> lo maneja el runner
        - el `if response.stop_reason != ...`   -> lo maneja el runner
        - `messages.append(...)` x2             -> lo maneja el runner
        - recorrer bloques buscando `tool_use`  -> lo maneja el runner
        - ejecutar y armar `tool_result`        -> lo maneja el runner

    Y mirá qué desapareció que NO querías que desapareciera:

        - el tope de iteraciones (el runner tiene el suyo, con otro default)
        - el `is_error` y el mensaje genérico que protegía tus credenciales
        - la traza: `tools_used`, `iterations`, tokens acumulados
        - la decisión de ejecutar o no: el runner ejecuta TODO lo que el
          modelo pida, sin pasar por vos

    Nada de eso es imposible con el runner —tiene hooks por turno para
    aprobación, logging e interceptar errores— pero hay que pedirlo. Por
    default, ejecuta.
    """
    runner = get_client().beta.messages.tool_runner(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=settings.ANTHROPIC_MAX_TOKENS,
        tools=TOOLS,
        messages=[{"role": "user", "content": prompt}],
    )

    # `until_done()` corre el loop entero: llama, ejecuta lo que el modelo pida,
    # le devuelve los resultados, y repite hasta que el modelo termine.
    final = runner.until_done()

    return " ".join(block.text.strip() for block in final.content if block.type == "text")
