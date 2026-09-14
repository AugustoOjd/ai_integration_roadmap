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
import time
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

from anthropic.types import Message, MessageParam, ToolUseBlock, Usage
from sqlalchemy.ext.asyncio import AsyncSession

from app.budget import BudgetExceededError, estimar, marcar_agotada, verificar
from app.config import settings
from app.context import ajustar
from app.deps import AgentDeps, RunContext
from app.llm import get_async_client
from app.models import ApprovalStatus, PendingApproval, SessionStatus
from app.policy import requiere_aprobacion
from app.repository import (
    ApprovalAlreadyDecidedError,
    ApprovalExpiredError,
    get_pending,
    get_session,
    load_history,
    next_turn,
    pause_turn,
    pendientes_de,
    record_step,
    resume_turn,
    save_turn,
)

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
# En el mini 8 esto era una constante de este módulo. Subió a `config.py` porque
# acá convive con el OTRO tope, el de presupuesto en tokens (Fase 7), y los dos
# son política operativa: se ajustan por entorno, no por deploy.
DEFAULT_MAX_ITERATIONS = settings.AGENT_MAX_ITERATIONS


class ApprovalRequired(Exception):
    """El loop se frenó: una tool sensible espera el sí o el no de un humano.

    No es un error y por eso no hereda de `RuntimeError`: nada salió mal. El
    request se aceptó, el trabajo no terminó, y hay otro recurso donde seguirlo
    — que es exactamente la definición de un 202 Accepted.

    Lleva las aprobaciones pendientes adentro para que el handler de `errors.py`
    pueda armar la respuesta sin volver a consultar la base.
    """

    def __init__(self, session_id: str, aprobaciones: list[PendingApproval]) -> None:
        self.session_id = session_id
        self.aprobaciones = aprobaciones
        super().__init__(
            f"la sesión {session_id} espera aprobación de "
            f"{[a.tool_name for a in aprobaciones]}"
        )


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


async def run_agent(
    db: AsyncSession,
    session_id: str,
    prompt: str,
    deps: AgentDeps,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
) -> AgentResult:
    """Un turno nuevo: el usuario habla y el agente responde.

    Todo el mini 9 cabe en la diferencia entre esta función y la del mini 8, y
    la diferencia son dos líneas: de dónde sale `messages` al empezar, y qué se
    hace con él al terminar. El motor —el `while stop_reason == "tool_use"`—
    está en `_correr_loop`, y es idéntico.
    """
    # El número de turno se reserva ANTES de arrancar, porque la traza (Fase 4)
    # se escribe vuelta a vuelta y cada paso tiene que decir a qué turno
    # pertenece — mucho antes de que `save_turn` exista para asignarlo.
    turno = await next_turn(db, session_id)

    # ------------------------------------------------------------- LA MEMORIA
    # El mini 8 arrancaba siempre en cero:
    #
    #     messages = [{"role": "user", "content": prompt}]
    #
    # Y eso no era una simplificación del mini: es cómo funciona la Messages
    # API. Es *stateless*. No guarda nada entre requests, no tiene noción de
    # conversación, no hay un `session_id` que mandarle. Si el agente recuerda
    # algo, es porque VOS se lo volvés a contar entero en cada llamada.
    #
    # De ahí sale el costo que se ve enseguida en los logs: el historial viaja
    # completo en cada vuelta y en cada turno, así que `input_tokens` crece sin
    # parar. No es un bug, es el precio de la memoria — y es lo que la Fase 7
    # acota y la Fase 8 recorta.
    historial = await load_history(db, session_id)
    nuevo_mensaje: MessageParam = {"role": "user", "content": prompt}

    return await _correr_loop(
        db,
        session_id,
        deps,
        turno=turno,
        messages=[*historial, nuevo_mensaje],
        # Lo que este turno le AGREGA al historial. Se lleva aparte de
        # `messages` porque al guardar hay que persistir sólo lo nuevo: el
        # historial viejo ya está en la base y reescribirlo duplicaría filas.
        nuevos=[nuevo_mensaje],
        max_iterations=max_iterations,
    )


async def _correr_loop(
    db: AsyncSession,
    session_id: str,
    deps: AgentDeps,
    *,
    turno: int,
    messages: list[MessageParam],
    nuevos: list[MessageParam],
    max_iterations: int,
) -> AgentResult:
    """El motor. El mismo `while` del mini 8, con dos puntos de entrada.

    Está extraído justamente por eso: `run_agent` entra con un mensaje del
    usuario, y `resume_run` (Fase 6) entra con un `tool_result` que llegó un
    request más tarde. Para el loop son indistinguibles — recibe un historial y
    sigue desde donde esté.

    Que esa indistinción sea posible es la propiedad que se busca en toda la
    fase: **retomar no es "seguir", es reconstruir**. Un loop que sólo se puede
    continuar desde la pila de Python no sobrevive a un reinicio; uno que se
    reconstruye desde la base, sí. Es el mismo requisito que va a imponer Celery
    en PROJECT 2.
    """
    client = get_async_client()

    # El sobre con el contexto autenticado, armado UNA vez por corrida y pasado
    # a cada tool que lo pida. Nada de esto entra al request que ve el modelo.
    ctx = RunContext(deps=deps, turn=turno)

    result = AgentResult(text="")

    # Se lee una vez, fuera del loop: los contadores de la fila no cambian
    # durante el turno (se persisten al final), y lo que sí cambia —el gasto de
    # este turno— se lleva en `result`.
    sesion = await get_session(db, session_id)

    tools = registry.to_params()

    for iteration in range(1, max_iterations + 1):
        result.iterations = iteration

        # ------------------------------------------------- EL TOPE DE GASTO
        # Antes de mandar, no después. `count_tokens` es gratis: preguntar
        # cuánto va a costar no puede costar.
        #
        # El `gastado_en_vuelo` es lo que este turno ya consumió y todavía no
        # está en la base. Sin ese término, la vuelta 3 chequearía contra un
        # contador que no se movió desde antes de la vuelta 1, y un solo turno
        # podría pasarse del presupuesto entero.
        #
        # Y antes de rechazar, se intenta RECORTAR (Fase 8). El orden importa:
        # un historial que no entra no es necesariamente un turno que haya que
        # abortar — casi siempre es un turno que arrastra `tool_result` viejos
        # que ya no le sirven a nadie.
        #
        # El límite es el menor de dos: lo que queda de presupuesto y lo que
        # entra en la ventana del modelo. Son topes distintos con la misma
        # unidad, y el que ate más corto es el que manda.
        limite = min(
            settings.CONTEXT_MAX_INPUT_TOKENS,
            max(0, sesion.budget_tokens - sesion.input_tokens_used - result.input_tokens),
        )

        async def medir(candidatos: list[MessageParam]) -> int:
            return await estimar(client, candidatos, tools)

        # OJO: se reasigna `messages` y NO `nuevos`. El recorte es de lo que se
        # manda, no de lo que se guarda — la base conserva el historial completo
        # porque es lo que se audita.
        messages, estimado = await ajustar(messages, limite=limite, medir=medir)

        try:
            verificar(sesion, estimado=estimado, gastado_en_vuelo=result.input_tokens)
        except BudgetExceededError:
            # Se cobra lo que este turno alcanzó a gastar. Sin esto, un turno
            # que se pasa en la vuelta 3 saldría GRATIS: el modelo trabajó dos
            # vueltas, el historial no se guarda, y nadie registra ese gasto.
            await marcar_agotada(
                db,
                session_id,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
            )
            raise

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
            #
            # Se calculan UNA vez arriba del loop, y no por vuelta como en el
            # mini 8: `estimar` necesita exactamente la misma lista, y dos
            # llamadas a `to_params()` que devolvieran algo distinto harían que
            # la estimación no corresponda al request.
            tools=tools,
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

            # La respuesta final también es parte del historial. Olvidarla acá
            # es el bug que hace que el agente "no recuerde lo que él mismo
            # dijo": el usuario pregunta "¿y por 3?" y el modelo no tiene su
            # propia respuesta anterior para saber de qué número habla.
            nuevos.append({"role": "assistant", "content": response.content})

            # ------------------------------------------------- GUARDAR, al final
            # Un solo `save_turn`, con el turno entero, en una transacción.
            #
            # Y sólo acá, en el camino feliz. Si el loop no converge, más abajo
            # levanta y NO se guarda nada: la sesión queda exactamente como
            # estaba. Es deliberado — el historial sólo acepta turnos completos.
            # Persistir un turno que quedó a mitad de camino dejaría al modelo
            # arrancando el turno siguiente desde un estado que él nunca vio
            # resuelto.
            await save_turn(
                db,
                session_id,
                nuevos,
                # El mismo número que usó la traza. Si `save_turn` lo recalculara
                # por su cuenta podrían discrepar, y el log diría "turno 3"
                # mientras los mensajes dicen "turno 4".
                turn=turno,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
            )
            return result

        # ---------------------------------------------- REGLA: reenviar TODO
        # La respuesta completa y sin tocar. Si filtrás bloques acá, el pedido
        # del modelo desaparece del historial y tu `tool_result` del turno
        # siguiente queda huérfano.
        #
        # Va a las dos listas: a `messages` porque es lo que se le manda al
        # modelo en la vuelta siguiente, y a `nuevos` porque es lo que hay que
        # persistir. Mantenerlas en paralelo es prolijo hasta la Fase 8, donde
        # se separan de verdad: ahí `messages` se recorta y `nuevos` no.
        turno_assistant: MessageParam = {"role": "assistant", "content": response.content}
        messages.append(turno_assistant)
        nuevos.append(turno_assistant)

        # Un turno puede traer VARIOS bloques `tool_use`: el paralelismo está
        # activado por default, y ante "¿qué hora es y cuánto es 100*2?" el
        # modelo pide las dos juntas.
        calls = [block for block in response.content if block.type == "tool_use"]

        # ------------------------------------------------- PAUSA POR APROBACIÓN
        # Antes de ejecutar nada, se mira si alguna de las tools pedidas es
        # sensible. Si lo es, el turno se congela acá: se persiste el estado y
        # el request termina con un 202.
        #
        # Y no se ejecuta NINGUNA, ni las inocentes del mismo turno. Dos razones:
        #
        #   1. Los `tool_result` de un turno van todos en UN mensaje. No podés
        #      mandar dos ahora y uno mañana, así que o se ejecutan todas o
        #      ninguna.
        #   2. Si la decisión es "no", el trabajo de las otras se tiró. Hacerlo
        #      después es gratis; deshacerlo, no siempre.
        sensibles = [call for call in calls if requiere_aprobacion(call.name)]
        if sensibles:
            logger.info(
                "pausando session=%s turno=%d por %s",
                session_id,
                turno,
                [call.name for call in sensibles],
            )

            aprobaciones = await pause_turn(
                db,
                session_id,
                nuevos,
                turn=turno,
                pendientes=[(c.id, c.name, dict(c.input)) for c in sensibles],
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
            )

            # Salida no local, igual que `MaxIterationsError`.
            #
            # Podría ser un campo de `AgentResult` —"status: pending"— y sería
            # más explícito. Es a propósito que no lo sea: con un campo, un
            # caller que se olvida de chequearlo devuelve una respuesta vacía
            # como si fuera un turno normal, y el bug es silencioso. Con una
            # excepción, olvidarse es imposible.
            raise ApprovalRequired(session_id, aprobaciones)

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
        # El contexto de ESTA vuelta. `replace` sobre un frozen dataclass copia
        # y cambia un campo: dos ints y una referencia, más barato que el
        # riesgo de que una tool vea un contexto mutando debajo suyo.
        ctx_vuelta = replace(ctx, iteration=iteration)

        tool_results = await asyncio.gather(
            *(
                _run_tool(
                    call,
                    ctx_vuelta,
                    # Los tokens del modelo son de la VUELTA, no de cada tool.
                    # Si se los pusiéramos a los tres pasos de una vuelta con
                    # tres tools, cualquier `sum(input_tokens)` sobre la traza
                    # contaría lo mismo tres veces. Se los queda el primero; en
                    # el resto quedan en NULL, que es lo honesto.
                    usage=response.usage if indice == 0 else None,
                )
                for indice, call in enumerate(calls)
            )
        )

        # ------------------------------------- REGLA: todos en UN SOLO mensaje
        # Los resultados de un turno van juntos, en un único mensaje `user`.
        #
        # Partirlos en varios mensajes no da error: da algo peor. El modelo lee
        # ese historial como el ejemplo de cómo se hacen las cosas acá, y turno
        # a turno aprende a NO pedir tools en paralelo. Degrada solo, se paga en
        # latencia, y nadie lo relaciona nunca con la causa.
        #
        # Por eso el `append` está FUERA de todo bucle.
        turno_resultados: MessageParam = {"role": "user", "content": list(tool_results)}
        messages.append(turno_resultados)
        nuevos.append(turno_resultados)

    # Si salimos del `for` sin haber retornado, el modelo seguía pidiendo tools
    # cuando se acabó el presupuesto. No devolvemos una respuesta a medias
    # haciéndola pasar por final: eso es peor que un error, porque es un error
    # que no se ve.
    #
    # Nuevo en este mini: acá NO se guardó nada. `save_turn` sólo se llama en el
    # camino feliz, así que el historial queda como estaba y el usuario puede
    # reintentar sobre una sesión sana. La alternativa —persistir el turno
    # trunco— dejaría en la base un `tool_result` que el modelo nunca llegó a
    # interpretar, y todo turno futuro arrancaría desde ese estado raro.
    raise MaxIterationsError(
        f"el agente no convergió en {max_iterations} iteraciones "
        f"(tools usadas: {result.tools_used})"
    )


async def resume_run(
    db: AsyncSession,
    session_id: str,
    tool_use_id: str,
    *,
    approved: bool,
    deps: AgentDeps,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
) -> AgentResult:
    """Retoma una corrida pausada. La fase difícil del mini.

    Lo que NO se hace acá es "continuar" nada: el `for` de la corrida original
    murió con aquel request. Lo que se hace es **reconstruir** — levantar el
    historial de la base, rearmar los bloques `tool_use` que quedaron abiertos,
    ejecutarlos (o no), y volver a entrar al mismo loop con el historial
    completo.

    Esa distinción es la que justifica que el loop sea nuestro y no de un
    framework. Un loop que sólo se puede continuar desde la pila de Python
    exige que el proceso siga vivo esperando a una persona que quizás conteste
    mañana; el worker se reinicia, el deploy pasa, la conexión se cae. Uno que
    se reconstruye desde la base no tiene ese requisito — y es exactamente lo
    que va a pedir Celery en PROJECT 2.
    """
    # El lock se toma primero y se sostiene toda la decisión: leer el pendiente,
    # marcarlo y ejecutar la tool tienen que ser atómicos respecto de otro
    # request que llegue con la misma decisión.
    sesion = await get_session(db, session_id, for_update=True)

    if sesion.status is not SessionStatus.PENDING_APPROVAL:
        # Aprobar algo en una sesión que no está esperando nada es un conflicto
        # de estado, no un "no encontrado".
        raise ApprovalAlreadyDecidedError(session_id)

    aprobacion = await get_pending(db, session_id, tool_use_id)

    # ---------------------------------------------------------- idempotencia
    # El `status` de la fila ES el candado. No alcanza con que el endpoint sea
    # "cuidadoso": dos clicks en un botón, un reintento de red o un cliente con
    # retry automático mandan el mismo POST dos veces, y acá "dos veces"
    # significa dos cancelaciones o dos reembolsos.
    if aprobacion.status is not ApprovalStatus.PENDING:
        raise ApprovalAlreadyDecidedError(tool_use_id)

    if aprobacion.expires_at < datetime.now(UTC):
        aprobacion.status = ApprovalStatus.EXPIRED
        aprobacion.decided_at = datetime.now(UTC)
        await db.commit()
        raise ApprovalExpiredError(tool_use_id)

    aprobacion.status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
    aprobacion.decided_at = datetime.now(UTC)

    # ¿Queda algo más por decidir en este turno? Un turno puede haber pedido dos
    # tools sensibles. Los `tool_result` van todos en un mensaje, así que no se
    # puede retomar hasta que estén todas resueltas.
    restantes = [
        p
        for p in await pendientes_de(db, session_id)
        if p.tool_use_id != tool_use_id
    ]
    if restantes:
        await db.commit()
        raise ApprovalRequired(session_id, restantes)

    # ------------------------------------------------------- RECONSTRUIR
    historial = await load_history(db, session_id)
    turno = aprobacion.turn
    ctx = RunContext(deps=deps, turn=turno, iteration=0)

    # El último mensaje del historial es el del assistant que quedó con los
    # `tool_use` abiertos. Sus bloques volvieron de JSONB como dicts, así que se
    # rearman como objetos del SDK: `_run_tool` habla ese idioma, y así el
    # camino de retomar usa EXACTAMENTE el mismo código que el camino normal.
    abiertos = [
        ToolUseBlock.model_validate(bloque)
        for bloque in historial[-1]["content"]
        if bloque["type"] == "tool_use"
    ]

    resultados: list[dict[str, Any]] = []
    for call in abiertos:
        if call.id == tool_use_id and not approved:
            # -------------------------------------------------- EL RECHAZO
            # No se borra el `tool_use` del historial: eso rompería el par y
            # dejaría la sesión inservible. Se le contesta con un `tool_result`
            # marcado como error, igual que cualquier fallo de tool.
            #
            # Y el modelo lo entiende: en la vuelta siguiente le explica al
            # usuario que no se hizo, o propone otra cosa. Es la misma mecánica
            # que la Fase 6 del mini 8 — un error de tool no es un error del
            # request, es información.
            texto = (
                f"El usuario NO autorizó la ejecución de {call.name!r}. "
                f"No la reintentes: explicale que la acción no se realizó."
            )
            resultados.append(_result_block(call.id, texto, is_error=True))
            await record_step(
                db,
                session_id=session_id,
                turn=turno,
                iteration=0,
                tool_name=call.name,
                tool_input=dict(call.input),
                tool_output="rechazada por el usuario",
                is_error=True,
            )
        else:
            # Aprobada, o una tool inocente del mismo turno que se había
            # diferido. Las dos corren ahora, por el camino de siempre.
            resultados.append(await _run_tool(call, ctx))

    mensaje_resultados: MessageParam = {"role": "user", "content": resultados}

    # Commit: la decisión, el efecto de la tool y el `tool_result` que lo
    # registra, juntos. Ver la nota en `resume_turn`.
    await resume_turn(db, session_id, mensaje_resultados, turn=turno)

    logger.info(
        "retomando session=%s turno=%d aprobada=%s", session_id, turno, approved
    )

    # Y de vuelta al mismo loop, con el historial ya completo. Para `_correr_loop`
    # esto es indistinguible de un turno normal.
    return await _correr_loop(
        db,
        session_id,
        deps,
        turno=turno,
        messages=[*historial, mensaje_resultados],
        # Vacío: lo que acabamos de generar ya está persistido. Lo que el loop
        # produzca de acá en adelante es lo que le queda por guardar.
        nuevos=[],
        max_iterations=max_iterations,
    )


async def _run_tool(
    call: ToolUseBlock,
    ctx: RunContext[AgentDeps],
    usage: Usage | None = None,
) -> dict[str, Any]:
    """Ejecuta una tool, deja su paso en la traza, y devuelve su `tool_result`.

    NUNCA levanta.

    Que no levante es un requisito del protocolo, no una preferencia de estilo:
    todo `tool_use` necesita su `tool_result` en el turno siguiente. Si una
    excepción se escapa de acá, `gather` la propaga, el turno se arma sin ese
    bloque, y la API rechaza el request entero — un fallo en una tool se
    convierte en un fallo de toda la conversación.
    """
    logger.info("  -> %s(%s)", call.name, call.input)

    # `perf_counter` y no `time.time()`: es un reloj monótono, pensado para medir
    # intervalos. `time.time()` puede saltar hacia atrás si NTP ajusta el reloj
    # del sistema, y entonces una tool "tarda" -40 ms.
    empezo = time.perf_counter()

    # Se arma acá, una vez, y se usa en los tres caminos de abajo. Lo único que
    # cambia entre ellos es el resultado.
    async def dejar_traza(salida: str, *, es_error: bool) -> None:
        await record_step(
            ctx.deps.db,
            session_id=ctx.deps.session_id,
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

    try:
        # El registry decide por dónde va cada tool: `await` directo si es
        # `async def` (las que usan la base lo son por necesidad), o un hilo si
        # es sincrónica. `asyncio.gather` sobre llamadas sincrónicas no
        # paraleliza nada —correrían una tras otra igual— y peor: una tool lenta
        # BLOQUEA el event loop y congela los demás requests del proceso.
        output = await registry.execute(call.name, dict(call.input), ctx)
        await dejar_traza(output, es_error=False)
        return _result_block(call.id, output)

    except ToolError as exc:
        # Fallo ESPERABLE: la tool no existe, o los argumentos no validan. El
        # mensaje está escrito para que lo lea el modelo, así que se lo pasamos
        # tal cual. En la vuelta siguiente corrige y reintenta.
        logger.warning("  !! %s: %s", call.name, exc)
        await dejar_traza(str(exc), es_error=True)
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

        # En la TRAZA sí va el detalle: la traza la leés vos, no el modelo. Es
        # la otra mitad de la decisión de arriba — el mismo fallo se cuenta
        # distinto según quién sea el lector.
        await dejar_traza("error interno (ver el log del servidor)", es_error=True)

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
