"""El agentic loop.

Un solo `while`: mientras el modelo pida tools, ejecutarlas, meterlas en el
historial y volver a llamarlo. Eso es, literalmente, un agente — el resto es
memoria, tools y prompts.
"""

import logging
import time
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

from anthropic.types import Message, MessageParam, ToolUseBlock, Usage
from sqlalchemy.orm import Session

from app.agent.budget import (
    BudgetExceededError,
    estimar,
    liberar,
    liquidar,
    marcar_agotada,
    reservar,
    verificar,
)
from app.agent.context import ajustar
from app.agent.deps import AgentDeps, RunContext
from app.agent.llm import get_client
from app.agent.policy import requiere_aprobacion
from app.agent.repository import (
    get_conversation,
    get_pending,
    load_history,
    next_turn,
    pause_turn,
    record_step,
    resume_turn,
    save_turn,
)
from app.core.config import settings
from app.core.models import ApprovalStatus, PendingApproval

# Importar app.tools es lo que dispara los decoradores y llena el registry.
from app.tools import registry
from app.tools.registry import ToolError

logger = logging.getLogger(__name__)

# Cuántas vueltas como máximo antes de rendirse.
#
# No es opcional: un modelo confundido puede pedir la misma tool para siempre —
# la tool devuelve algo que no le sirve y en vez de rendirse la reintenta con
# otros argumentos. Sin tope es un loop infinito que quema tokens a velocidad de
# red y no se ve hasta la factura.
#
# Si un agente legítimamente necesita 30 vueltas, el problema no es el tope: son
# las tools, demasiado granulares.
DEFAULT_MAX_ITERATIONS = settings.AGENT_MAX_ITERATIONS


class ApprovalRequired(Exception):
    """El loop se frenó: una tool sensible espera el sí o el no de un humano.

    No es un error y por eso no hereda de RuntimeError: nada salió mal. El request
    se aceptó, el trabajo no terminó, y hay otro recurso donde seguirlo — que es la
    definición de un 202.

    Lleva las aprobaciones adentro para que el handler pueda armar la respuesta sin
    volver a consultar la base.
    """

    def __init__(self, conversation_id: str, aprobaciones: list[PendingApproval]) -> None:
        self.conversation_id = conversation_id
        self.aprobaciones = aprobaciones
        super().__init__(
            f"la conversación {conversation_id} espera aprobación de "
            f"{[a.tool_name for a in aprobaciones]}"
        )


class RunCancelled(Exception):
    """Alguien pidió frenar la corrida y el loop llegó a un punto seguro.

    No hereda de RuntimeError: nada falló. Es una salida ordenada, igual que
    `ApprovalRequired`.

    Lleva la vuelta en la que cortó porque es el dato que importa después: saber
    si alcanzó a ejecutar tools o se frenó antes de la primera llamada.
    """

    def __init__(self, conversation_id: str, iteration: int) -> None:
        self.conversation_id = conversation_id
        self.iteration = iteration
        super().__init__(f"corrida cancelada en la vuelta {iteration}")


class MaxIterationsError(RuntimeError):
    """El agente no llegó a una respuesta final dentro del presupuesto de vueltas.

    Clase propia y no un ValueError genérico porque se mapea a un código HTTP
    distinto: no es culpa del cliente (400) ni del proveedor (503), es que la tarea
    no convergió.
    """


@dataclass(slots=True)
class AgentResult:
    """Lo que devuelve una corrida.

    El texto final es lo que le interesa al usuario; el resto es lo que te interesa
    a vos cuando algo sale mal. Un agente sin estos campos es una caja negra.
    """

    text: str
    # En orden de invocación y con repetidos: si el modelo llamó `calculate` tres
    # veces, querés verlo tres veces. Un set escondería justo el síntoma que estás
    # buscando.
    tools_used: list[str] = field(default_factory=list)
    iterations: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


def run_agent(
    db: Session,
    conversation_id: str,
    prompt: str,
    deps: AgentDeps,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
) -> AgentResult:
    """Un turno nuevo: el usuario habla y el agente responde."""
    # El número de turno se reserva antes de arrancar porque la traza se escribe
    # vuelta a vuelta y cada paso tiene que decir a qué turno pertenece, mucho
    # antes de que save_turn exista para asignarlo.
    turno = next_turn(db, conversation_id)

    # La Messages API es stateless: no guarda nada entre requests, no tiene noción
    # de conversación, no hay un conversation_id que mandarle. Si el agente recuerda
    # algo es porque vos se lo volvés a contar entero en cada llamada.
    #
    # De ahí el costo que se ve en los logs: el historial viaja completo en cada
    # vuelta y en cada turno, así que input_tokens crece sin parar. No es un bug,
    # es el precio de la memoria.
    historial = load_history(db, conversation_id)
    nuevo_mensaje: MessageParam = {"role": "user", "content": prompt}

    return _correr_loop(
        db,
        conversation_id,
        deps,
        turno=turno,
        messages=[*historial, nuevo_mensaje],
        # Lo que este turno le AGREGA al historial. Se lleva aparte de `messages`
        # porque al guardar hay que persistir sólo lo nuevo: el historial viejo ya
        # está en la base y reescribirlo duplicaría filas.
        nuevos=[nuevo_mensaje],
        max_iterations=max_iterations,
    )


def _correr_loop(
    db: Session,
    conversation_id: str,
    deps: AgentDeps,
    *,
    turno: int,
    messages: list[MessageParam],
    nuevos: list[MessageParam],
    max_iterations: int,
) -> AgentResult:
    """El motor, con dos puntos de entrada.

    `run_agent` entra con un mensaje del usuario y `resume_run` con un tool_result
    que llegó un request más tarde. Para el loop son indistinguibles: recibe un
    historial y sigue desde donde esté.

    Esa indistinción es la propiedad que se busca: retomar no es "seguir", es
    reconstruir. Un loop que sólo se puede continuar desde la pila de Python no
    sobrevive a un reinicio; uno que se reconstruye desde la base, sí.
    """
    client = get_client()

    # El sobre con el contexto autenticado, armado una vez por corrida y pasado a
    # cada tool que lo pida. Nada de esto entra al request que ve el modelo.
    ctx = RunContext(deps=deps, turn=turno)

    result = AgentResult(text="")

    # Se lee una vez, fuera del loop: los contadores de la fila no cambian durante
    # el turno (se persisten al final) y lo que sí cambia se lleva en `result`.
    conversacion = get_conversation(db, conversation_id)

    tools = registry.to_params()

    for iteration in range(1, max_iterations + 1):
        result.iterations = iteration

        # ---- El punto seguro -------------------------------------------------
        #
        # Acá y en ningún otro lado: antes de llamar al modelo y antes de ejecutar
        # nada. No hay una tool a mitad de camino ni un `tool_use` esperando su
        # resultado, así que cortar deja el historial consistente.
        #
        # La alternativa —matar el proceso con `revoke(terminate=True)`— funciona
        # en el sentido de que la tarea deja de correr, y deja atrás un `tool_use`
        # sin su `tool_result`: la conversación queda rota para siempre y el
        # síntoma aparece un request después.
        #
        # El precio de esperar al punto seguro es la latencia de la llamada en
        # curso, unos segundos. Es barato.
        # Señal de vida, antes de meterse en la llamada al modelo. Si el proceso
        # muere ahí adentro, éste es el último latido que va a quedar — y la
        # distancia entre él y `now()` es lo que delata al worker muerto.
        if deps.latir is not None:
            deps.latir()

        if deps.cancelado is not None and deps.cancelado():
            logger.info(
                "cancelando conversation=%s turno=%d en la vuelta %d",
                conversation_id,
                turno,
                iteration,
            )
            record_step(
                conversation_id=conversation_id,
                task_id=deps.task_id,
                turn=turno,
                iteration=iteration,
                # No es una tool: es un evento de la corrida. El nombre entre
                # paréntesis lo distingue de cualquier tool real en un `group by`.
                tool_name="(cancelada)",
                tool_input={},
                tool_output="cancelada por pedido del usuario",
            )
            # Nada de lo que este turno generó se persiste: `save_turn` sólo corre
            # en el camino feliz. La conversación queda exactamente como estaba.
            raise RunCancelled(conversation_id, iteration)

        # El límite es el menor de dos topes con la misma unidad: lo que queda de
        # presupuesto y lo que entra en la ventana del modelo. Manda el que ate más
        # corto.
        limite = min(
            settings.CONTEXT_MAX_INPUT_TOKENS,
            max(
                0,
                conversacion.budget_tokens
                - conversacion.input_tokens_used
                - result.input_tokens,
            ),
        )

        def medir(candidatos: list[MessageParam]) -> int:
            return estimar(client, candidatos, tools)

        # Antes de rechazar por presupuesto se intenta RECORTAR. El orden importa:
        # un historial que no entra casi nunca es un turno que haya que abortar,
        # casi siempre es un turno que arrastra tool_result viejos que ya no le
        # sirven a nadie.
        #
        # Se reasigna `messages` y NO `nuevos`: el recorte es de lo que se manda, no
        # de lo que se guarda.
        messages, estimado = ajustar(messages, limite=limite, medir=medir)

        try:
            verificar(conversacion, estimado=estimado, gastado_en_vuelo=result.input_tokens)
        except BudgetExceededError:
            # Se cobra lo que este turno alcanzó a gastar. Sin esto, un turno que se
            # pasa en la vuelta 3 saldría gratis: el modelo trabajó dos vueltas, el
            # historial no se guarda, y nadie registra ese gasto.
            marcar_agotada(
                db,
                conversation_id,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
            )
            raise

        # ---- El presupuesto del USUARIO ---------------------------------
        #
        # El de la conversación ya se chequeó arriba y acota este hilo. Éste acota
        # a la persona, y cruza conversaciones y workers: hace falta reservar
        # ANTES de llamar, porque el que llega segundo tiene que enterarse de que
        # no entra sin haber gastado nada.
        #
        # Los dos topes conviven y gana el que ate más corto.
        if not reservar(db, deps.user_id, estimado):
            marcar_agotada(
                db,
                conversation_id,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
            )
            raise BudgetExceededError(necesarios=estimado, disponibles=0)

        try:
            response: Message = client.messages.create(
                model=settings.ANTHROPIC_MODEL,
                max_tokens=settings.ANTHROPIC_MAX_TOKENS,
                messages=messages,
                # Las tools van en cada request: no son estado de la conversación,
                # si las sacás en la vuelta 3 el modelo deja de poder pedirlas.
                #
                # Se calculan una sola vez arriba del loop porque `estimar`
                # necesita exactamente la misma lista: dos llamadas a to_params()
                # que devolvieran algo distinto harían que la estimación no
                # corresponda al request. Y porque la caché de prompts es un match
                # por prefijo, donde un solo byte distinto acá invalida todo lo que
                # venga después.
                tools=tools,
            )
        except BaseException:
            # Lo apartado no se gastó: devolverlo. Sin esto, cada timeout le come
            # presupuesto al usuario por una llamada que nunca ocurrió — y como la
            # ventana dura una hora, el efecto se acumula.
            liberar(db, deps.user_id, estimado)
            raise

        # Se liquida con el input REAL, que puede diferir del estimado: el
        # recorte de contexto pudo haber cambiado el request entre la estimación y
        # el envío.
        liquidar(db, deps.user_id, estimado, response.usage.input_tokens)

        # El usage es por request, no acumulado. Sumarlo acá es la única forma de
        # saber qué costó la corrida entera. Mirá cómo crece input_tokens vuelta a
        # vuelta: la vuelta 3 paga otra vez todo lo que ya pagaron la 1 y la 2.
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

        # El control de flujo del agente es `stop_reason`, no "¿ya usé una tool?"
        # ni "¿hay texto en la respuesta?". Cualquier cosa que no sea 'tool_use'
        # significa que el modelo terminó de generar y no hay nada que ejecutar.
        if response.stop_reason != "tool_use":
            if response.stop_reason == "max_tokens":
                # Se cortó a la mitad: el texto puede ser una frase partida. Se avisa
                # en vez de devolverlo como si fuera una respuesta completa.
                logger.warning("respuesta truncada por max_tokens")
            result.text = _text_of(response)

            # La respuesta final también es parte del historial. Olvidarla acá es el
            # bug que hace que el agente "no recuerde lo que él mismo dijo": el
            # usuario pregunta "¿y por 3?" y el modelo no tiene su propia respuesta
            # anterior para saber de qué número habla.
            nuevos.append({"role": "assistant", "content": response.content})

            # Un solo save_turn, con el turno entero, en una transacción, y sólo en
            # el camino feliz. Si el loop no converge, más abajo levanta y no se
            # guarda nada: la conversación queda como estaba. Persistir un turno a medias
            # dejaría al modelo arrancando el siguiente desde un estado que él nunca
            # vio resuelto.
            save_turn(
                db,
                conversation_id,
                nuevos,
                # El mismo número que usó la traza. Si save_turn lo recalculara por
                # su cuenta podrían discrepar, y el log diría "turno 3" mientras los
                # mensajes dicen "turno 4".
                turn=turno,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
            )
            return result

        # La respuesta completa y sin tocar. Si filtrás bloques acá, el pedido del
        # modelo desaparece del historial y tu tool_result del turno siguiente queda
        # huérfano.
        #
        # Va a las dos listas: a `messages` porque es lo que se le manda al modelo en
        # la vuelta siguiente, y a `nuevos` porque es lo que hay que persistir.
        turno_assistant: MessageParam = {"role": "assistant", "content": response.content}
        messages.append(turno_assistant)
        nuevos.append(turno_assistant)

        # Un turno puede traer varios bloques tool_use: el paralelismo está activado
        # por default, y ante "¿qué hora es y cuánto es 100*2?" el modelo pide las dos
        # juntas.
        calls = [block for block in response.content if block.type == "tool_use"]

        # Antes de ejecutar nada se mira si alguna tool pedida es sensible. Si lo es,
        # el turno se congela: se persiste el estado y el request termina con un 202.
        #
        # Y no se ejecuta ninguna, ni las inocentes del mismo turno. Dos razones: los
        # tool_result de un turno van todos en UN mensaje, así que o se ejecutan todas
        # o ninguna; y si la decisión es "no", el trabajo de las otras se tiró —
        # hacerlo después es gratis, deshacerlo no siempre.
        sensibles = [call for call in calls if requiere_aprobacion(call.name)]
        if sensibles:
            logger.info(
                "pausando conversation=%s turno=%d por %s",
                conversation_id,
                turno,
                [call.name for call in sensibles],
            )

            aprobaciones = pause_turn(
                db,
                conversation_id,
                nuevos,
                turn=turno,
                pendientes=[(c.id, c.name, dict(c.input)) for c in sensibles],
                task_id=deps.task_id,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
            )

            # Salida no local a propósito. Con un campo "status: pending" en
            # AgentResult, un caller que se olvida de chequearlo devuelve una
            # respuesta vacía como si fuera un turno normal y el bug es silencioso.
            # Con una excepción, olvidarse es imposible.
            raise ApprovalRequired(conversation_id, aprobaciones)

        # Los nombres se registran antes de ejecutar, en el orden original de los
        # bloques: así tools_used dice qué pidió el modelo y no en qué orden
        # terminaron las tools.
        result.tools_used.extend(call.name for call in calls)

        # El contexto de esta vuelta. `replace` sobre un frozen dataclass copia y
        # cambia un campo: dos ints y una referencia, más barato que el riesgo de que
        # una tool vea un contexto mutando debajo suyo.
        ctx_vuelta = replace(ctx, iteration=iteration)

        # Las tools de una vuelta corren EN SERIE. Son independientes —el modelo las
        # pidió juntas, así que ninguna necesita el resultado de otra— y en principio
        # se podrían paralelizar, pero no con hilos: comparten la Session de
        # SQLAlchemy, que no es thread-safe. Paralelizarlas exigiría una conexión por
        # tool, y para tres tools de 200 ms no vale la complejidad.
        tool_results = [
            _run_tool(
                call,
                ctx_vuelta,
                # Los tokens del modelo son de la VUELTA, no de cada tool. Si se los
                # pusiéramos a los tres pasos de una vuelta con tres tools, cualquier
                # sum(input_tokens) sobre la traza contaría lo mismo tres veces. Se los
                # queda el primero; en el resto quedan en NULL, que es lo honesto.
                usage=response.usage if indice == 0 else None,
            )
            for indice, call in enumerate(calls)
        ]

        # Los resultados de un turno van juntos, en un único mensaje `user`.
        #
        # Partirlos en varios mensajes no da error: da algo peor. El modelo lee ese
        # historial como el ejemplo de cómo se hacen las cosas acá, y turno a turno
        # aprende a NO pedir tools en paralelo. Degrada solo, se paga en latencia, y
        # nadie lo relaciona nunca con la causa.
        turno_resultados: MessageParam = {"role": "user", "content": list(tool_results)}
        messages.append(turno_resultados)
        nuevos.append(turno_resultados)

    # Salimos del for sin retornar: el modelo seguía pidiendo tools cuando se acabó
    # el presupuesto de vueltas. No devolvemos una respuesta a medias haciéndola
    # pasar por final — eso es peor que un error, porque es un error que no se ve.
    #
    # Acá no se guardó nada: save_turn sólo se llama en el camino feliz, así que el
    # historial queda como estaba y el usuario puede reintentar sobre una conversación
    # sana.
    raise MaxIterationsError(
        f"el agente no convergió en {max_iterations} iteraciones "
        f"(tools usadas: {result.tools_used})"
    )


def resume_run(
    db: Session,
    conversation_id: str,
    tool_use_id: str,
    *,
    deps: AgentDeps,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
) -> AgentResult:
    """Retoma una corrida pausada, con la decisión YA tomada.

    No se "continúa" nada: el `for` de la corrida original murió con aquel request.
    Se reconstruye — se levanta el historial de la base, se rearman los bloques
    tool_use que quedaron abiertos, se ejecutan (o no), y se vuelve a entrar al
    mismo loop con el historial completo.

    Esa distinción es la que justifica que el loop sea nuestro. Un loop que sólo se
    puede continuar desde la pila de Python exige que el proceso siga vivo esperando
    a una persona que quizás conteste mañana.

    **No decide**: lee de la fila qué se decidió. Desde que la retoma corre en un
    worker, decidir y ejecutar pasan en procesos distintos — el request registra
    el sí o el no (`decidir_aprobacion`) y esto viene después, quizás segundos
    después, quizás tras un reintento.

    Que estén separados también los hace recuperables por separado: si el worker
    muere entre la decisión y la ejecución, la decisión ya es durable y volver a
    correr esto es seguro — la tool con efectos está detrás del candado del
    `tool_use_id`.
    """
    aprobacion = get_pending(db, conversation_id, tool_use_id)

    if aprobacion.status not in (ApprovalStatus.APPROVED, ApprovalStatus.REJECTED):
        # Bug de programación: alguien llamó a retomar sin decidir antes.
        raise RuntimeError(
            f"la aprobación {tool_use_id} está en {aprobacion.status.value!r}: "
            f"hay que decidirla antes de retomar"
        )

    approved = aprobacion.status is ApprovalStatus.APPROVED

    historial = load_history(db, conversation_id)
    turno = aprobacion.turn
    ctx = RunContext(deps=deps, turn=turno, iteration=0)

    # El último mensaje del historial es el del assistant que quedó con los tool_use
    # abiertos. Sus bloques volvieron de JSONB como dicts, así que se rearman como
    # objetos del SDK: _run_tool habla ese idioma, y así retomar usa exactamente el
    # mismo código que el camino normal.
    abiertos = [
        ToolUseBlock.model_validate(bloque)
        for bloque in historial[-1]["content"]
        if bloque["type"] == "tool_use"
    ]

    resultados: list[dict[str, Any]] = []
    for call in abiertos:
        if call.id == tool_use_id and not approved:
            # No se borra el tool_use del historial: eso rompería el par y dejaría la
            # conversación inservible. Se le contesta con un tool_result marcado como error,
            # igual que cualquier fallo de tool, y el modelo lo entiende — en la vuelta
            # siguiente le explica al usuario que no se hizo, o propone otra cosa.
            texto = (
                f"El usuario NO autorizó la ejecución de {call.name!r}. "
                f"No la reintentes: explicale que la acción no se realizó."
            )
            resultados.append(_result_block(call.id, texto, is_error=True))
            record_step(
                conversation_id=conversation_id,
                task_id=deps.task_id,
                turn=turno,
                iteration=0,
                tool_name=call.name,
                tool_input=dict(call.input),
                tool_output="rechazada por el usuario",
                is_error=True,
            )
        else:
            # Aprobada, o una tool inocente del mismo turno que se había diferido.
            resultados.append(_run_tool(call, ctx))

    mensaje_resultados: MessageParam = {"role": "user", "content": resultados}

    # Commit: la decisión, el efecto de la tool y el tool_result que lo registra,
    # juntos. Ver la nota en resume_turn.
    resume_turn(db, conversation_id, mensaje_resultados, turn=turno)

    logger.info(
        "retomando conversation=%s turno=%d aprobada=%s", conversation_id, turno, approved
    )

    # Y de vuelta al mismo loop, con el historial ya completo. Para _correr_loop esto
    # es indistinguible de un turno normal.
    return _correr_loop(
        db,
        conversation_id,
        deps,
        turno=turno,
        messages=[*historial, mensaje_resultados],
        # Vacío: lo que acabamos de generar ya está persistido. Lo que el loop
        # produzca de acá en adelante es lo que le queda por guardar.
        nuevos=[],
        max_iterations=max_iterations,
    )


def _run_tool(
    call: ToolUseBlock,
    ctx: RunContext[AgentDeps],
    usage: Usage | None = None,
) -> dict[str, Any]:
    """Ejecuta una tool, deja su paso en la traza, y devuelve su tool_result.

    NUNCA levanta, y es un requisito del protocolo: todo tool_use necesita su
    tool_result en el turno siguiente. Si una excepción se escapa de acá, el turno
    se arma sin ese bloque y la API rechaza el request entero — un fallo en una tool
    se convierte en un fallo de toda la conversación.
    """
    logger.info("  -> %s(%s)", call.name, call.input)

    # perf_counter y no time.time(): es un reloj monótono, pensado para medir
    # intervalos. time.time() puede saltar hacia atrás si NTP ajusta el reloj del
    # sistema, y entonces una tool "tarda" -40 ms.
    empezo = time.perf_counter()

    def dejar_traza(salida: str, *, es_error: bool) -> None:
        record_step(
            conversation_id=ctx.deps.conversation_id,
            task_id=ctx.deps.task_id,
            turn=ctx.turn,
            iteration=ctx.iteration,
            tool_name=call.name,
            tool_input=dict(call.input),
            tool_output=salida,
            is_error=es_error,
            latency_ms=int((time.perf_counter() - empezo) * 1000),
            input_tokens=usage.input_tokens if usage else None,
            output_tokens=usage.output_tokens if usage else None,
        )

    # El contexto de ESTA tool, con el id del bloque que la pidió. Es la clave
    # del candado de idempotencia, y viaja por el contexto —no por los
    # argumentos— por el mismo motivo que el `user_id`: no es algo que el modelo
    # elija, es algo que el servidor sabe.
    ctx = replace(ctx, tool_use_id=call.id)

    try:
        output = registry.execute(call.name, dict(call.input), ctx)
        dejar_traza(output, es_error=False)
        return _result_block(call.id, output)

    except ToolError as exc:
        # Fallo esperable: la tool no existe, o los argumentos no validan. El mensaje
        # está escrito para que lo lea el modelo, así que se lo pasamos tal cual y en
        # la vuelta siguiente corrige.
        logger.warning("  !! %s: %s", call.name, exc)
        dejar_traza(str(exc), es_error=True)
        return _result_block(call.id, str(exc), is_error=True)

    except Exception:
        # Fallo inesperado: un bug en la tool, un servicio caído, un timeout.
        #
        # El traceback completo va al log del servidor, que es lo que vas a necesitar
        # para arreglarlo. Al modelo se le manda un mensaje genérico, sin str(exc): un
        # traceback puede contener rutas, queries y connection strings, y todo lo que
        # entra en un tool_result el modelo lo puede repetir en su respuesta final.
        logger.exception("  !! error inesperado en %s", call.name)

        # En la traza sí va el detalle: la traza la leés vos, no el modelo. El mismo
        # fallo se cuenta distinto según quién sea el lector.
        dejar_traza("error interno (ver el log del servidor)", es_error=True)

        return _result_block(
            call.id,
            f"la tool {call.name!r} falló por un error interno. "
            f"No reintentes con los mismos argumentos.",
            is_error=True,
        )


def _result_block(tool_use_id: str, content: str, *, is_error: bool = False) -> dict[str, Any]:
    """Arma un bloque tool_result.

    Éxito y error tienen la misma forma y cambia un flag: para el protocolo un error
    no es la ausencia de un resultado, es un resultado con otro contenido. Sin el
    flag, un mensaje de error parece la respuesta de la tool y el modelo se lo cree.
    """
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": content,
        "is_error": is_error,
    }


def _text_of(response: Message) -> str:
    """Junta los bloques de texto de una respuesta.

    Son varios y no uno porque el modelo puede intercalar texto con otros bloques.
    """
    return " ".join(block.text.strip() for block in response.content if block.type == "text")
