"""El historial, de la base a la API y de vuelta.

Guardar el historial parece trivial: una fila por mensaje. El problema es QUÉ se
guarda. El mensaje que devuelve la API es una lista de bloques:

    [TextBlock(text="Voy a calcularlo"),
     ToolUseBlock(id="toolu_7", name="calculate", input={...})]

Si persistís sólo el texto —la tentación, porque es lo legible— en el turno
siguiente le mandás al modelo un historial donde el tool_result existe pero su
tool_use no, y la API contesta:

    messages.N: tool_use ids were found without tool_result blocks

De ahí la regla: el historial se persiste tal cual viaja. La vista legible para
un humano es una proyección, no el dato.

El loop no habla SQL: habla con este módulo. Esa frontera es lo que permite
retomar una corrida desde un request distinto sin que el agente se entere de que
hubo un viaje a Postgres en el medio.
"""

from datetime import UTC, datetime
from typing import Any

from anthropic.types import MessageParam
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agent.policy import TTL_APROBACION
from app.core.models import (
    ApprovalStatus,
    Conversation,
    ConversationStatus,
    ExecutionStep,
    Message,
    PendingApproval,
)

# Cuánto de la salida de una tool se guarda en la traza. Una tool que devuelve
# 200 KB infla esta tabla igual que infla el contexto, con la diferencia de que
# acá nadie lo va a leer entero.
MAX_TOOL_OUTPUT_CHARS = 2_000


class ConversationNotFoundError(LookupError):
    """La conversación no existe. Se traduce a 404."""


class ApprovalNotFoundError(LookupError):
    """No hay ningún pedido de aprobación con ese tool_use_id. Se traduce a 404."""


class ApprovalAlreadyDecidedError(RuntimeError):
    """Ya se decidió. Se traduce a 409.

    Es el guardián de idempotencia: dos POST con el mismo tool_use_id no pueden
    ejecutar la tool dos veces, y "dos veces" significa dos cancelaciones, dos
    mails, dos reembolsos.
    """


class ApprovalExpiredError(RuntimeError):
    """El pedido venció sin decisión. Se traduce a 409."""


class ConversationPausedError(RuntimeError):
    """Llegó un mensaje a una conversación que espera una aprobación. Se traduce a 409.

    Error de dominio propio porque no es "no existe" ni "no es tuya": la conversación
    existe, es tuya, y aun así este pedido no se puede atender ahora.
    """


# ---------------------------------------------------------------------------
# Serialización de bloques
# ---------------------------------------------------------------------------


def dump_blocks(content: Any) -> list[dict[str, Any]]:
    """Convierte el `content` de un mensaje a algo que JSONB pueda guardar.

    El content llega mezclado: lo que devuelve la API son objetos Pydantic del SDK
    (TextBlock, ToolUseBlock) y lo que escribís vos —los tool_result— ya son
    dicts.

    `mode="json"` fuerza a que los tipos que JSON no conoce se conviertan acá,
    donde el error sería obvio, en vez de explotar dentro del driver a diez frames
    de distancia.

    `exclude_none=True` saca los campos opcionales vacíos (un `citations: null`,
    por ejemplo). Lo que se guarda acá se le vuelve a mandar a la API, y mandarle
    nulls en campos que no usás es pedirle que los interprete. Los None que estén
    dentro del `input` de una tool no se tocan: ese campo es del modelo.
    """
    # La API acepta content como string suelto por comodidad, y es la forma en que
    # naturalmente armás el mensaje del usuario. Se normaliza a bloques antes de
    # guardar para que la columna tenga una sola forma posible.
    #
    # Sin esta rama el bug es silencioso: un string es iterable, así que el `for`
    # de abajo lo recorrería letra por letra y guardaría una lista de caracteres.
    if isinstance(content, str):
        return [{"type": "text", "text": content}]

    bloques: list[dict[str, Any]] = []
    for bloque in content:
        if isinstance(bloque, BaseModel):
            bloques.append(bloque.model_dump(mode="json", exclude_none=True))
        else:
            # Ya es un dict: un tool_result armado por nosotros, o un historial que
            # acaba de salir de la base.
            bloques.append(dict(bloque))
    return bloques


# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------


def load_history(db: Session, conversation_id: str) -> list[MessageParam]:
    """El historial completo de una conversación, listo para `messages.create(...)`.

    Devuelve MessageParam y no filas del ORM: quien llama es el loop, y el loop
    piensa en el vocabulario de la Messages API. Si cambia el modelo de datos,
    cambia este módulo y nada más.

    El ORDER BY position no es decorativo: un tool_result antes de su tool_use es
    un request rechazado.
    """
    consulta = (
        select(Message.role, Message.content)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.position)
    )
    filas = db.execute(consulta).all()

    # Sólo las dos columnas que se usan, sin instanciar objetos del ORM ni meterlos
    # en el mapa de identidad. En un historial largo la diferencia se nota.
    return [{"role": fila.role, "content": fila.content} for fila in filas]


def get_conversation(
    db: Session,
    conversation_id: str,
    *,
    user_id: str | None = None,
    for_update: bool = False,
) -> Conversation:
    """Trae la conversación, o levanta ConversationNotFoundError.

    Con `user_id`, el filtro por dueño va en la misma query: un conversation_id es
    adivinable, y sin ese filtro cualquiera que acierte uno lee la conversación de
    otro. Y falla como "no existe" y no como "no es tuyo", para que el endpoint no
    sea un oráculo de qué conversaciones existen.

    Con `for_update=True` agrega un SELECT ... FOR UPDATE, que toma un lock sobre
    la fila hasta el final de la transacción. Cierra una carrera concreta: dos
    requests de la misma conversación a la vez leen la misma "última posición", escriben
    ahí, y el UniqueConstraint(conversation_id, position) hace fallar a uno. Es un lock
    por conversación, no global.
    """
    consulta = select(Conversation).where(Conversation.id == conversation_id)
    if user_id is not None:
        consulta = consulta.where(Conversation.user_id == user_id)
    if for_update:
        consulta = consulta.with_for_update()

    conversacion = db.execute(consulta).scalar_one_or_none()
    if conversacion is None:
        raise ConversationNotFoundError(conversation_id)
    return conversacion


def next_turn(db: Session, conversation_id: str) -> int:
    """Qué número de turno le toca al próximo.

    Se necesita antes de correr el loop porque la traza se escribe vuelta a vuelta
    y cada paso tiene que decir a qué turno pertenece, mucho antes de que
    `save_turn` exista para asignarlo.

    Se reserva sin lock, de forma optimista. Protegerlo con un lock obligaría a
    retenerlo durante todas las llamadas al modelo —segundos— y serializaría la
    conversación entera contra la latencia de Anthropic. El historial, que es lo
    que no puede romperse, sigue protegido por el UniqueConstraint de `position` y
    por el FOR UPDATE de `save_turn`.
    """
    consulta = select(func.coalesce(func.max(Message.turn), 0)).where(
        Message.conversation_id == conversation_id
    )
    return db.execute(consulta).scalar_one() + 1


# ---------------------------------------------------------------------------
# La traza
# ---------------------------------------------------------------------------


def record_step(
    *,
    conversation_id: str,
    task_id: str | None,
    turn: int,
    iteration: int,
    tool_name: str,
    tool_input: dict[str, Any],
    tool_output: str | None,
    is_error: bool = False,
    latency_ms: int | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> None:
    """Deja un paso de la traza y lo commitea en el acto, en su PROPIA sesión.

    Dos decisiones, y la segunda arregla un agujero real.

    **Commit inmediato.** Va contra el instinto de "una transacción por request",
    y es el punto: si el loop explota en la vuelta 3, las vueltas 1 y 2 son
    justamente lo que vas a querer mirar. Y es lo que hace que la traza sea
    consultable **mientras la tarea corre**, que es toda esta fase.

    **Sesión propia.** Antes commiteaba sobre la sesión del loop, y eso arrastraba
    lo que hubiera pendiente ahí. El caso concreto: `cancel_order` hace `flush` de
    la cancelación y de su reserva de idempotencia, y el `record_step` que venía
    justo después las commiteaba — antes de que existiera el `tool_result` que las
    registra. Si el loop moría en el medio, quedaba un pedido cancelado que el
    historial no menciona.

    Con conexión propia, el commit de la traza no toca la transacción del turno:
    el efecto de la tool y la prueba de ese efecto siguen commiteando juntos, en
    `save_turn` o en `resume_turn`.

    El precio es una conexión más por paso. Vale: la alternativa era un agujero de
    consistencia que sólo aparece cuando algo ya salió mal.
    """
    if tool_output is not None and len(tool_output) > MAX_TOOL_OUTPUT_CHARS:
        sobrante = len(tool_output) - MAX_TOOL_OUTPUT_CHARS
        tool_output = f"{tool_output[:MAX_TOOL_OUTPUT_CHARS]}... [+{sobrante} chars]"

    # Import local: `db` importa config y modelos, y este módulo lo importa el
    # loop. Traerlo arriba no es un ciclo hoy, pero ata el repositorio al engine
    # global — y lo que hace testeable al resto de este módulo es justamente que
    # reciba la sesión de afuera.
    from app.core.db import SessionFactory

    with SessionFactory() as traza:
        traza.add(
            ExecutionStep(
                conversation_id=conversation_id,
                task_id=task_id,
                turn=turn,
                iteration=iteration,
                tool_name=tool_name,
                tool_input=tool_input,
                tool_output=tool_output,
                is_error=is_error,
                latency_ms=latency_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
        )
        traza.commit()


def load_task_steps(db: Session, task_id: str) -> list[ExecutionStep]:
    """Los pasos de UNA ejecución, en orden.

    Es la consulta del polling: corre cada pocos segundos mientras la tarea vive,
    y devuelve más filas cada vez porque `record_step` commitea vuelta a vuelta.
    Sin ese commit inmediato esto devolvería una lista vacía hasta el final, que
    es justo cuando ya no hace falta.
    """
    return list(
        db.execute(
            select(ExecutionStep)
            .where(ExecutionStep.task_id == task_id)
            .order_by(ExecutionStep.id)
        )
        .scalars()
        .all()
    )


def load_steps(
    db: Session, conversation_id: str, *, limit: int = 100, before_id: int | None = None
) -> list[ExecutionStep]:
    """La traza de una conversación, más nueva primero.

    Paginada por cursor y no por OFFSET: con offset, mientras alguien pagina, un
    paso nuevo al principio corre todo hacia atrás y la página 2 repite filas de la
    1. Un cursor sobre una columna monótona no tiene ese problema y además no
    obliga a la base a contar y descartar las filas que saltea.
    """
    consulta = (
        select(ExecutionStep)
        .where(ExecutionStep.conversation_id == conversation_id)
        .order_by(ExecutionStep.id.desc())
        .limit(limit)
    )
    if before_id is not None:
        consulta = consulta.where(ExecutionStep.id < before_id)

    return list(db.execute(consulta).scalars().all())


def conversation_stats(db: Session, conversation_id: str) -> dict[str, Any]:
    """Resumen agregado de la traza de una conversación.

    Se calcula en la base con GROUP BY y no trayendo todas las filas a Python. La
    diferencia no se nota con 10 pasos y se nota mucho con 10.000 — y la versión en
    Python deja de ser exacta en cuanto la traza se pagine.
    """
    consulta = (
        select(
            ExecutionStep.tool_name,
            func.count().label("veces"),
            # `filter (where ...)` es el agregado condicional de SQL estándar:
            # cuenta sólo las filas que cumplen, en la misma pasada.
            func.count().filter(ExecutionStep.is_error).label("errores"),
            func.coalesce(func.sum(ExecutionStep.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(ExecutionStep.output_tokens), 0).label("output_tokens"),
        )
        .where(ExecutionStep.conversation_id == conversation_id)
        .group_by(ExecutionStep.tool_name)
        .order_by(func.count().desc())
    )
    filas = db.execute(consulta).all()

    return {
        "total_steps": sum(fila.veces for fila in filas),
        "failed_steps": sum(fila.errores for fila in filas),
        "tools": {fila.tool_name: fila.veces for fila in filas},
        "input_tokens": sum(fila.input_tokens for fila in filas),
        "output_tokens": sum(fila.output_tokens for fila in filas),
    }


# ---------------------------------------------------------------------------
# Escritura
# ---------------------------------------------------------------------------


def _append_messages(
    db: Session,
    conversation_id: str,
    nuevos: list[MessageParam],
    turn: int | None,
) -> int:
    """Agrega mensajes al final del historial. NO commitea, NO toma el lock.

    Extraído para que save_turn y pause_turn compartan exactamente la misma lógica
    de posiciones: duplicarla sería garantizar que un día se desincronicen, y el
    síntoma es un historial desordenado, que es un request rechazado.

    Asume que quien llama ya tomó el lock sobre la conversación. Es un contrato implícito
    y por eso la función es privada.
    """
    # Una sola query para las dos coordenadas. `coalesce` cubre la conversación vacía,
    # donde max() devuelve NULL y no 0: sin él, el primer turno de cada conversación
    # fallaría al sumarle 1 a None.
    consulta = select(
        func.coalesce(func.max(Message.position), -1),
        func.coalesce(func.max(Message.turn), 0),
    ).where(Message.conversation_id == conversation_id)
    ultima_posicion, ultimo_turno = db.execute(consulta).one()

    # El turno puede venir dado: el loop lo reservó al empezar porque la traza lo
    # necesita vuelta a vuelta. Si no viene, se calcula acá.
    turno = turn if turn is not None else ultimo_turno + 1

    db.add_all(
        Message(
            conversation_id=conversation_id,
            turn=turno,
            position=ultima_posicion + offset,
            role=mensaje["role"],
            content=dump_blocks(mensaje["content"]),
        )
        for offset, mensaje in enumerate(nuevos, start=1)
    )
    return turno


def pause_turn(
    db: Session,
    conversation_id: str,
    nuevos: list[MessageParam],
    *,
    turn: int,
    pendientes: list[tuple[str, str, dict[str, Any]]],
    task_id: str | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> list[PendingApproval]:
    """Congela una corrida a mitad de camino, esperando una decisión humana.

    Guarda tres cosas y las guarda juntas, en una transacción:

      1. El turno hasta acá, incluido el mensaje del assistant con los bloques
         tool_use que no se ejecutaron.
      2. Una fila por tool sensible pendiente.
      3. El estado de la conversación en pending_approval.

    Que sean atómicas es todo: si el historial se guardara y los pendientes no,
    quedaría una conversación ACTIVA con un tool_use huérfano, y el turno siguiente le
    mandaría a la API un request inválido.

    Esto persiste un tool_use sin su tool_result, que es justo lo que la regla del
    historial prohíbe. No es una contradicción sino una precisión del invariante:
    lo que vale no es "el historial nunca tiene pares abiertos" sino "una conversación
    ACTIVA tiene un historial válido". Una conversación en pending_approval no es válida
    para mandarle a la API, y por eso rechaza mensajes nuevos con 409.

    La alternativa sería no persistir el turno y guardar el `messages` entero como
    JSON dentro del pendiente. Es peor: duplica el historial en dos lugares con
    formatos distintos, y el día que difieran no vas a saber cuál vale.
    """
    conversacion = get_conversation(db, conversation_id, for_update=True)

    turno = _append_messages(db, conversation_id, nuevos, turn)

    ahora = datetime.now(UTC)
    aprobaciones = [
        PendingApproval(
            conversation_id=conversation_id,
            task_id=task_id,
            tool_use_id=tool_use_id,
            turn=turno,
            tool_name=tool_name,
            tool_input=tool_input,
            expires_at=ahora + TTL_APROBACION,
        )
        for tool_use_id, tool_name, tool_input in pendientes
    ]
    db.add_all(aprobaciones)

    # Mientras el estado diga esto, mandar un mensaje devuelve 409.
    conversacion.status = ConversationStatus.PENDING_APPROVAL

    # Los tokens ya gastados se cobran igual: el modelo trabajó, que la corrida
    # haya quedado en pausa no se lo devuelve nadie.
    conversacion.input_tokens_used += input_tokens
    conversacion.output_tokens_used += output_tokens

    db.commit()
    return aprobaciones


def pendientes_de(
    db: Session, conversation_id: str, *, only_pending: bool = True
) -> list[PendingApproval]:
    """Las aprobaciones de una conversación. Por default, sólo las que siguen abiertas."""
    consulta = select(PendingApproval).where(
        PendingApproval.conversation_id == conversation_id
    )
    if only_pending:
        consulta = consulta.where(PendingApproval.status == ApprovalStatus.PENDING)
    return list(db.execute(consulta.order_by(PendingApproval.id)).scalars().all())


def pendientes_de_tarea(db: Session, task_id: str) -> list[PendingApproval]:
    """Las aprobaciones abiertas de una ejecución."""
    return list(
        db.execute(
            select(PendingApproval)
            .where(
                PendingApproval.task_id == task_id,
                PendingApproval.status == ApprovalStatus.PENDING,
            )
            .order_by(PendingApproval.id)
        )
        .scalars()
        .all()
    )


def get_pending(db: Session, conversation_id: str, tool_use_id: str) -> PendingApproval:
    """Trae un pedido de aprobación concreto, o levanta.

    Se busca por (conversation_id, tool_use_id) y no por un id propio de la fila porque
    ése es el identificador que el cliente tiene: se lo dimos en el 202, y es el
    mismo que va a llevar el tool_result cuando se arme.
    """
    consulta = select(PendingApproval).where(
        PendingApproval.conversation_id == conversation_id,
        PendingApproval.tool_use_id == tool_use_id,
    )
    aprobacion = db.execute(consulta).scalar_one_or_none()
    if aprobacion is None:
        raise ApprovalNotFoundError(tool_use_id)
    return aprobacion


def decidir_aprobacion(
    db: Session, conversation_id: str, tool_use_id: str, *, approved: bool
) -> PendingApproval:
    """Registra el sí o el no. No ejecuta nada.

    Está separada de la ejecución porque a partir de esta fase las dos pasan en
    **procesos distintos**: el request decide, un worker retoma. Y el orden
    importa — la decisión se persiste primero, así dos POST simultáneos no pueden
    encolar dos retomas.

    El lock sobre la conversación se sostiene toda la función: leer el pendiente y
    marcarlo tienen que ser atómicos respecto de otro request con la misma
    decisión.
    """
    conversacion = get_conversation(db, conversation_id, for_update=True)

    if conversacion.status is not ConversationStatus.PENDING_APPROVAL:
        # Decidir sobre una conversación que no espera nada es un conflicto de
        # estado, no un "no encontrado".
        raise ApprovalAlreadyDecidedError(conversation_id)

    aprobacion = get_pending(db, conversation_id, tool_use_id)

    # El status de la fila ES el candado. No alcanza con que el endpoint sea
    # cuidadoso: dos clicks, un reintento de red o un cliente con retry automático
    # mandan el mismo POST dos veces, y acá "dos veces" significa dos
    # cancelaciones o dos reembolsos.
    if aprobacion.status is not ApprovalStatus.PENDING:
        raise ApprovalAlreadyDecidedError(tool_use_id)

    if aprobacion.expires_at < datetime.now(UTC):
        aprobacion.status = ApprovalStatus.EXPIRED
        aprobacion.decided_at = datetime.now(UTC)
        db.commit()
        raise ApprovalExpiredError(tool_use_id)

    aprobacion.status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
    aprobacion.decided_at = datetime.now(UTC)
    db.commit()
    return aprobacion


def expirar_vencidas(db: Session) -> list[PendingApproval]:
    """Cierra las aprobaciones que nadie decidió a tiempo. Devuelve cuáles.

    Sin esto, un pendiente de hace una semana sigue siendo aprobable: alguien
    autoriza el martes un "cancelá el pedido 991" que el agente propuso el
    viernes, cuando el pedido ya se entregó.

    Con un humano mirando el 202 esto molestaba; sin nadie mirando, se acumulan.
    """
    vencidas = list(
        db.execute(
            select(PendingApproval).where(
                PendingApproval.status == ApprovalStatus.PENDING,
                PendingApproval.expires_at < datetime.now(UTC),
            )
        )
        .scalars()
        .all()
    )
    ahora = datetime.now(UTC)
    for aprobacion in vencidas:
        aprobacion.status = ApprovalStatus.EXPIRED
        aprobacion.decided_at = ahora
    if vencidas:
        db.commit()
    return vencidas


def resume_turn(
    db: Session,
    conversation_id: str,
    mensaje_resultados: MessageParam,
    *,
    turn: int,
) -> None:
    """Cierra la pausa: guarda los tool_result y reactiva la conversación.

    Es una unidad de trabajo propia y commitea sola. Cuando se aprueba,
    `cancel_order` corre y hace flush: el pedido queda cancelado en esta
    transacción. Si esperáramos al save_turn del final y el loop fallara, pasaría
    una de dos cosas malas: se pierde la cancelación, o un record_step posterior la
    commitea sin su tool_result y queda un pedido cancelado que el historial no
    registra.

    Commiteando acá, el efecto de la tool y la prueba de ese efecto entran juntos.

    No toca expires_at ni el status del pendiente: eso ya lo hizo quien decidió, en
    esta misma transacción.
    """
    conversacion = get_conversation(db, conversation_id, for_update=True)

    _append_messages(db, conversation_id, [mensaje_resultados], turn)

    # El historial volvió a tener todos sus pares cerrados, así que la conversación ya
    # puede recibir mensajes.
    conversacion.status = ConversationStatus.ACTIVE

    db.commit()


def save_turn(
    db: Session,
    conversation_id: str,
    nuevos: list[MessageParam],
    *,
    turn: int | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> int:
    """Persiste un turno COMPLETO en una sola transacción. Devuelve su número.

    Un turno es un mensaje del usuario y todo lo que el loop generó respondiéndolo:
    puede ser uno o siete mensajes.

    Que sea una transacción es el punto: si commiteás mensaje por mensaje y el
    proceso muere en el medio, dejás persistido un tool_use sin su tool_result. Esa
    conversación no queda incompleta, queda ROTA para siempre, porque cada request futuro
    le manda a la API un historial inválido. No hay reintento que la arregle.

    Los tokens del turno se acumulan acá adentro, en la misma transacción, por la
    misma razón: un contador de gasto que puede desincronizarse del historial que
    lo causó no sirve para decidir nada.
    """
    # El lock se toma ANTES de leer las posiciones: entre el SELECT max(...) y el
    # INSERT hay una ventana, y este lock es lo que la cierra.
    conversacion = get_conversation(db, conversation_id, for_update=True)

    turno = _append_messages(db, conversation_id, nuevos, turn)

    # Acumular con += en Python en vez de un UPDATE ... SET x = x + n es correcto
    # sólo porque el FOR UPDATE de arriba serializó a los escritores de esta
    # conversación. Sin ese lock sería un lost update clásico: dos transacciones leen
    # 100, las dos escriben 150, y se perdió un turno de gasto.
    conversacion.input_tokens_used += input_tokens
    conversacion.output_tokens_used += output_tokens

    db.commit()
    return turno
