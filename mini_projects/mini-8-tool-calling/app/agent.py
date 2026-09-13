"""El agentic loop (Fases 3 y 6).

Las fases 1 y 2 asumieron UNA tool y UN round-trip. En la vida real el modelo
encadena: preguntar la hora, calcular sobre esa hora, y recién ahí contestar.
Eso no se resuelve con más `if`, se resuelve con un loop:

    mientras el modelo pida tools:
        ejecutarlas, meterlas en el historial, volver a llamarlo

Eso es, literalmente, un agente. El mini 9 no le agrega magia: le agrega
memoria, más tools y mejores prompts. El motor es este `while`.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from anthropic.types import Message, MessageParam, ToolUseBlock

from app.config import settings
from app.llm import get_async_client

# Importar `app.tools` es lo que dispara los decoradores y llena el registry.
from app.tools import registry
from app.tools.registry import ToolError

logger = logging.getLogger(__name__)

# Cuántas vueltas como máximo antes de rendirse.
#
# No es opcional. Un modelo confundido puede pedir la misma tool para siempre
# (típico: la tool devuelve algo que no le sirve, y en vez de rendirse la
# reintenta con otros argumentos, una y otra vez). Sin tope eso es un loop
# infinito que quema tokens a velocidad de red y no lo ves hasta la factura.
#
# 5 alcanza de sobra para tareas de este mini. Si tu agente legítimamente
# necesita 30 vueltas, el problema no es el tope: son las tools, que están
# demasiado granulares.
DEFAULT_MAX_ITERATIONS = 5


class MaxIterationsError(RuntimeError):
    """El agente no llegó a una respuesta final dentro del presupuesto.

    Tiene clase propia y no es un ValueError genérico porque en la Fase 7 se
    mapea a un código HTTP distinto del resto: no es culpa del cliente (400) ni
    del proveedor (503), es que la tarea no convergió.
    """


@dataclass(slots=True)
class AgentResult:
    """Lo que devuelve una corrida.

    El texto final es lo que le interesa al usuario; todo lo demás es lo que te
    interesa a VOS cuando algo sale mal. Un agente sin estos campos es una caja
    negra: no podés explicar por qué contestó lo que contestó, ni cuánto costó.
    """

    text: str
    # En orden de invocación y CON repetidos: si el modelo llamó `calculate`
    # tres veces, querés verlo tres veces. Un `set` te escondería justo el
    # síntoma que estás buscando.
    tools_used: list[str] = field(default_factory=list)
    iterations: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


async def run_agent(prompt: str, max_iterations: int = DEFAULT_MAX_ITERATIONS) -> AgentResult:
    """Corre el loop hasta que el modelo deje de pedir tools."""
    client = get_async_client()

    # El estado de toda la conversación. Vive acá, en tu proceso: la API no
    # guarda nada entre requests.
    messages: list[MessageParam] = [{"role": "user", "content": prompt}]
    result = AgentResult(text="")

    for iteration in range(1, max_iterations + 1):
        result.iterations = iteration

        response: Message = await client.messages.create(
            model=settings.ANTHROPIC_MODEL,
            max_tokens=settings.ANTHROPIC_MAX_TOKENS,
            messages=messages,
            # Las tools van en CADA request. No son estado de la conversación:
            # si las sacás en la vuelta 3, el modelo deja de poder pedirlas.
            #
            # Se recalculan por vuelta, pero el resultado es idéntico en todas:
            # mismo orden, mismos bytes. Eso importa para la caché de prompts,
            # que es un match por prefijo — un solo byte distinto acá invalida
            # todo lo que venga después.
            tools=registry.to_params(),
        )

        # El `usage` es por request, no acumulado. Sumarlo acá es la única forma
        # de saber qué costó la corrida ENTERA. Mirá cómo crece `input_tokens`
        # vuelta a vuelta: el historial se reenvía completo cada vez, así que la
        # vuelta 3 paga otra vez todo lo que ya pagaron la 1 y la 2.
        result.input_tokens += response.usage.input_tokens
        result.output_tokens += response.usage.output_tokens

        logger.info(
            "iteración %d/%d stop_reason=%s in=%d out=%d",
            iteration,
            max_iterations,
            response.stop_reason,
            response.usage.input_tokens,
            response.usage.output_tokens,
        )

        # ------------------------------------------------ la condición de salida
        # ESTE es el control de flujo del agente. No "¿ya usé una tool?", no
        # "¿hay texto en la respuesta?": `stop_reason`.
        #
        # Cualquier cosa que no sea 'tool_use' significa que el modelo terminó
        # de generar por algún motivo, y no hay nada que ejecutar.
        if response.stop_reason != "tool_use":
            if response.stop_reason == "max_tokens":
                # Se cortó a la mitad. El texto que haya está truncado y puede
                # ser una frase partida al medio. Avisamos en vez de devolverlo
                # como si fuera una respuesta completa.
                logger.warning("respuesta truncada por max_tokens")
            result.text = _text_of(response)
            return result

        # ---------------------------------------------- REGLA: reenviar TODO
        # La respuesta completa y sin tocar. Si filtrás bloques acá, el pedido
        # del modelo desaparece del historial y tu `tool_result` del turno
        # siguiente queda huérfano.
        messages.append({"role": "assistant", "content": response.content})

        # Un turno puede traer VARIOS bloques `tool_use`: el paralelismo está
        # activado por default, y ante "¿qué hora es y cuánto es 100*2?" el
        # modelo pide las dos juntas.
        calls = [block for block in response.content if block.type == "tool_use"]

        # Los nombres se registran ANTES de ejecutar, recorriendo los bloques en
        # su orden original. Si los agregaras dentro de las corrutinas, el orden
        # dependería de cuál termine primero — y `tools_used` dejaría de decir
        # qué pidió el modelo para pasar a decir qué tool fue más rápida.
        result.tools_used.extend(call.name for call in calls)

        # ------------------------------------------------- ejecución concurrente
        # `gather` las lanza todas y espera a que terminen todas. Si el modelo
        # pidió tres tools de 200 ms, la vuelta tarda 200 ms y no 600.
        #
        # Es correcto justamente porque son independientes: el modelo las pidió
        # en el mismo turno, o sea que ninguna necesita el resultado de otra.
        # Cuando SÍ hay dependencia, el modelo no las pide juntas — pide una,
        # ve el resultado, y en la vuelta siguiente pide la otra. Esa es la
        # diferencia entre una vuelta con tres tools y tres vueltas con una.
        tool_results = await asyncio.gather(*(_run_tool(call) for call in calls))

        # ------------------------------------- REGLA: todos en UN SOLO mensaje
        # Los resultados de un turno van juntos, en un único mensaje `user`.
        #
        # Partirlos en varios mensajes no da error: da algo peor. El modelo lee
        # ese historial como el ejemplo de cómo se hacen las cosas acá, y turno
        # a turno aprende a NO pedir tools en paralelo. Degrada solo, se paga en
        # latencia, y nadie lo relaciona nunca con la causa.
        #
        # Por eso el `append` está FUERA de todo bucle.
        messages.append({"role": "user", "content": list(tool_results)})

    # Si salimos del `for` sin haber retornado, el modelo seguía pidiendo tools
    # cuando se acabó el presupuesto. No devolvemos una respuesta a medias
    # haciéndola pasar por final: eso es peor que un error, porque es un error
    # que no se ve.
    raise MaxIterationsError(
        f"el agente no convergió en {max_iterations} iteraciones "
        f"(tools usadas: {result.tools_used})"
    )


async def _run_tool(call: ToolUseBlock) -> dict[str, Any]:
    """Ejecuta una tool y devuelve su bloque `tool_result`. NUNCA levanta.

    Que no levante es un requisito del protocolo, no una preferencia de estilo:
    todo `tool_use` necesita su `tool_result` en el turno siguiente. Si una
    excepción se escapa de acá, `gather` la propaga, el turno se arma sin ese
    bloque, y la API rechaza el request entero — un fallo en una tool se
    convierte en un fallo de toda la conversación.
    """
    logger.info("  -> %s(%s)", call.name, call.input)

    try:
        # Las tools son funciones SÍNCRONAS. `asyncio.gather` sobre llamadas
        # sincrónicas no paraleliza nada: correrían una tras otra igual, porque
        # nunca le devuelven el control al event loop. Peor: una tool lenta lo
        # BLOQUEA, congelando todos los demás requests del proceso.
        #
        # `to_thread` las manda a un hilo aparte, que es lo que las vuelve
        # concurrentes de verdad. (Si una tool fuera async nativa —un `httpx`
        # asíncrono, por ejemplo— se la esperaría directo con `await`.)
        output = await asyncio.to_thread(registry.execute, call.name, dict(call.input))
        return _result_block(call.id, output)

    except ToolError as exc:
        # Fallo ESPERABLE: la tool no existe, o los argumentos no validan. El
        # mensaje está escrito para que lo lea el modelo, así que se lo pasamos
        # tal cual. En la vuelta siguiente corrige y reintenta.
        logger.warning("  !! %s: %s", call.name, exc)
        return _result_block(call.id, str(exc), is_error=True)

    except Exception:
        # Fallo INESPERADO: un bug en la tool, un servicio caído, un timeout.
        #
        # Dos decisiones acá:
        #
        # 1. `logger.exception` guarda el traceback completo del lado del
        #    servidor. Eso es lo que vas a necesitar para arreglarlo.
        # 2. Al modelo le mandamos un mensaje GENÉRICO, sin `str(exc)`.
        #    Un traceback puede contener rutas del filesystem, queries SQL,
        #    connection strings con credenciales. Y todo lo que entra en un
        #    `tool_result` el modelo lo puede repetir en su respuesta final,
        #    que va directo al usuario. El detalle va al log; al modelo, lo
        #    mínimo para que pueda reaccionar.
        logger.exception("  !! error inesperado en %s", call.name)
        return _result_block(
            call.id,
            f"la tool {call.name!r} falló por un error interno. "
            f"No reintentes con los mismos argumentos.",
            is_error=True,
        )


def _result_block(tool_use_id: str, content: str, *, is_error: bool = False) -> dict[str, Any]:
    """Arma un bloque `tool_result`.

    Éxito y error tienen la MISMA forma —cambia un flag— y eso es a propósito:
    para el protocolo un error no es la ausencia de un resultado, es un
    resultado con otro contenido. `is_error: True` le dice al modelo "esto
    falló, no lo trates como un dato válido"; sin ese flag, un mensaje de error
    parece la respuesta de la tool y el modelo se lo cree.
    """
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": content,
        "is_error": is_error,
    }


def _text_of(response: Message) -> str:
    """Junta los bloques de texto de una respuesta.

    Son varios y no uno porque el modelo puede intercalar texto con otros
    bloques. `strip()` en cada uno y join con espacio para que no queden
    pegados ni con sangrías raras.
    """
    return " ".join(block.text.strip() for block in response.content if block.type == "text")
