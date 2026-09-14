"""Fase 1 — el historial, de la base a la API y de vuelta.

Ésta es la fase donde el mini se rompe si te apurás, así que va sola y antes que
el loop con memoria.

Guardar el historial parece trivial: una fila por mensaje. El problema es QUÉ
guardás. El mensaje que te devolvió la API es una lista de bloques:

    [TextBlock(text="Voy a calcularlo"),
     ToolUseBlock(id="toolu_7", name="calculate", input={...})]

Si persistís sólo `"Voy a calcularlo"` —la tentación, porque es lo legible— en
el turno siguiente le mandás al modelo un historial donde el `tool_result`
existe pero su `tool_use` no, y la API contesta:

    messages.N: tool_use ids were found without tool_result blocks

De ahí la regla de esta fase: **el historial se persiste tal cual viaja.** La
vista legible para un humano es una proyección (Fase 4), no el dato.

El loop no habla SQL: habla con este módulo. Esa frontera es lo que permite que
en la Fase 6 una corrida se retome desde un request distinto sin que el agente
se entere de que hubo un viaje a Postgres en el medio.
"""

from datetime import UTC, datetime
from typing import Any

from anthropic.types import MessageParam
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ApprovalStatus,
    ChatSession,
    ExecutionStep,
    Message,
    PendingApproval,
    SessionStatus,
)
from app.policy import TTL_APROBACION

# Cuánto de la salida de una tool se guarda en la traza.
#
# Una tool que devuelve 200 KB infla esta tabla igual que infla el contexto —
# con la diferencia de que acá nadie lo va a leer entero. 2000 caracteres
# alcanzan para entender qué pasó; el dato completo, si hace falta, está en el
# sistema de donde salió.
MAX_TOOL_OUTPUT_CHARS = 2_000


class SessionNotFoundError(LookupError):
    """La sesión no existe. La ruta lo traduce a un 404."""


class ApprovalNotFoundError(LookupError):
    """No hay ningún pedido de aprobación con ese `tool_use_id`. Se traduce a 404."""


class ApprovalAlreadyDecidedError(RuntimeError):
    """Ya se decidió. Se traduce a 409.

    Es el guardián de idempotencia: dos `POST` de aprobación con el mismo
    `tool_use_id` no pueden ejecutar la tool dos veces. Y "dos veces" acá
    significa dos cancelaciones, dos mails, dos reembolsos.
    """


class ApprovalExpiredError(RuntimeError):
    """El pedido venció sin decisión. Se traduce a 409.

    Aprobar el martes un "cancelá el pedido 991" que el agente propuso el
    viernes anterior es ejecutar una acción con el contexto de otro momento. El
    pedido puede haberse entregado en el medio.
    """


class SessionPausedError(RuntimeError):
    """Llegó un mensaje a una sesión que espera una aprobación. Se traduce a 409.

    Hace falta como error de dominio propio porque no es "no existe" ni "no es
    tuya": la sesión existe, es tuya, y aun así este pedido no se puede atender
    ahora. Es un conflicto con el estado del recurso.
    """


# ---------------------------------------------------------------------------
# Serialización de bloques
# ---------------------------------------------------------------------------


def dump_blocks(content: Any) -> list[dict[str, Any]]:
    """Convierte el `content` de un mensaje a algo que JSONB pueda guardar.

    El `content` llega mezclado y eso es normal:

      - Lo que devuelve la API son objetos Pydantic del SDK (`TextBlock`,
        `ToolUseBlock`).
      - Lo que escribís vos —los `tool_result`— ya son dicts.

    `mode="json"` (y no el default `mode="python"`) importa: fuerza a que los
    tipos que JSON no conoce se conviertan ahora, acá, donde el error sería
    obvio, en vez de explotar dentro del driver como un `Object of type X is not
    JSON serializable` a diez frames de distancia.

    `exclude_none=True` saca los campos opcionales que vinieron vacíos (un
    `citations: null` en un bloque de texto, por ejemplo). No es cosmética: lo
    que se guarda acá se le vuelve a mandar a la API, y mandarle nulls en campos
    que no usás es pedirle que los interprete. Los valores None que estén DENTRO
    del `input` de una tool no se tocan — ese campo es un dict libre y su
    contenido es del modelo, no nuestro.
    """
    # La API acepta `content` como un string suelto por comodidad
    # (`{"role": "user", "content": "hola"}`), y es la forma en que naturalmente
    # armás el mensaje del usuario. Acá se normaliza a bloques ANTES de guardar,
    # y no al leer: así la columna tiene una sola forma posible y nadie río
    # abajo tiene que preguntarse cuál de las dos le tocó.
    #
    # Sin esta rama el bug es silencioso y desconcertante: un string es
    # iterable, así que el `for` de abajo lo recorrería letra por letra y
    # guardaría una lista de caracteres.
    if isinstance(content, str):
        return [{"type": "text", "text": content}]

    bloques: list[dict[str, Any]] = []
    for bloque in content:
        if isinstance(bloque, BaseModel):
            bloques.append(bloque.model_dump(mode="json", exclude_none=True))
        else:
            # Ya es un dict (un `tool_result` armado por nosotros, o un
            # historial que acaba de salir de la base).
            bloques.append(dict(bloque))
    return bloques


# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------


async def load_history(db: AsyncSession, session_id: str) -> list[MessageParam]:
    """El historial completo de una sesión, listo para `messages.create(...)`.

    Devuelve `MessageParam` (dicts `{"role", "content"}`) y no filas del ORM a
    propósito: quien llama es el loop, y el loop piensa en el vocabulario de la
    Messages API, no en el de SQLAlchemy. Si algún día cambia el modelo de
    datos, cambia este módulo y nada más.

    El `ORDER BY position` no es decorativo. El orden del historial es parte de
    su validez: un `tool_result` antes de su `tool_use` es un request rechazado,
    no un detalle estético.
    """
    consulta = (
        select(Message.role, Message.content)
        .where(Message.session_id == session_id)
        .order_by(Message.position)
    )
    filas = (await db.execute(consulta)).all()

    # `select(Message.role, Message.content)` en vez de `select(Message)`: sólo
    # se traen las dos columnas que se usan, sin instanciar objetos del ORM ni
    # meterlos en el mapa de identidad de la sesión. En un historial largo, esa
    # diferencia se nota.
    return [{"role": fila.role, "content": fila.content} for fila in filas]


async def get_session(
    db: AsyncSession,
    session_id: str,
    *,
    user_id: str | None = None,
    for_update: bool = False,
) -> ChatSession:
    """Trae la sesión, o levanta `SessionNotFoundError`.

    Con `user_id`, el filtro por dueño va en la MISMA query. Es la regla de la
    Fase 3 aplicada a la conversación entera: un `session_id` es adivinable, y
    sin este filtro cualquiera que acierte uno lee la conversación de otro.

    Y falla como "no existe", no como "no es tuyo". Distinguirlos convertiría al
    endpoint en un oráculo: probando ids se podría averiguar qué sesiones
    existen sin poder verlas. Misma razón por la que un login dice "credenciales
    inválidas" y no "ese usuario no existe".

    Con `for_update=True` agrega un `SELECT ... FOR UPDATE`, que toma un lock
    sobre esa fila hasta que la transacción termine. Sirve para una carrera muy
    concreta: dos requests de la MISMA sesión llegando a la vez. Sin lock, los
    dos leen la misma "última posición", los dos escriben ahí, y el
    `UniqueConstraint(session_id, position)` hace fallar a uno con un error de
    integridad feo.

    Con lock, el segundo simplemente espera al primero y lee las posiciones ya
    actualizadas. Es un lock por sesión, no global: dos usuarios distintos no se
    estorban.
    """
    consulta = select(ChatSession).where(ChatSession.id == session_id)
    if user_id is not None:
        consulta = consulta.where(ChatSession.user_id == user_id)
    if for_update:
        consulta = consulta.with_for_update()

    sesion = (await db.execute(consulta)).scalar_one_or_none()
    if sesion is None:
        raise SessionNotFoundError(session_id)
    return sesion


async def next_turn(db: AsyncSession, session_id: str) -> int:
    """Qué número de turno le toca al próximo.

    Se necesita ANTES de correr el loop porque la traza de la Fase 4 se escribe
    vuelta a vuelta, y cada paso tiene que decir a qué turno pertenece — mucho
    antes de que `save_turn` exista para asignarlo.

    Se reserva de forma optimista, sin lock. Dos turnos concurrentes de la misma
    sesión podrían sacar el mismo número, y la traza quedaría confusa. No se
    protege con un lock acá porque el lock habría que retenerlo durante TODAS
    las llamadas al modelo —segundos— y eso serializaría la conversación entera
    contra la latencia de Anthropic. El historial, que es lo que no puede
    romperse, sigue protegido por el `UniqueConstraint` de `position` y por el
    `FOR UPDATE` de `save_turn`.
    """
    consulta = select(func.coalesce(func.max(Message.turn), 0)).where(
        Message.session_id == session_id
    )
    return (await db.execute(consulta)).scalar_one() + 1


# ---------------------------------------------------------------------------
# La traza (Fase 4)
# ---------------------------------------------------------------------------


async def record_step(
    db: AsyncSession,
    *,
    session_id: str,
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
    """Deja un paso de la traza, y lo COMMITEA en el acto.

    El commit inmediato es la decisión de la función, y va contra el instinto de
    "una transacción por request". El motivo: si el loop explota en la vuelta 3,
    las vueltas 1 y 2 son justamente lo que vas a querer mirar. Una traza que
    desaparece cuando algo sale mal sirve exactamente para los casos en los que
    no la necesitás.

    Es seguro commitear acá porque durante el loop no hay nada más pendiente en
    esta sesión de base: `save_turn` agrega los mensajes recién al final, en una
    transacción propia. Si algún día alguien agrega escrituras antes del loop,
    este commit se las llevaría puestas — de ahí la nota.

    La alternativa más robusta es una sesión de base aparte, con su propia
    conexión, totalmente independiente de la del request. No está acá por dos
    razones concretas: duplica conexiones por corrida, y rompe el aislamiento
    transaccional de los tests (una sesión nueva escribiría de verdad, fuera del
    rollback del `conftest`). En un sistema donde la auditoría es un requisito
    legal, esa independencia sí se paga.
    """
    if tool_output is not None and len(tool_output) > MAX_TOOL_OUTPUT_CHARS:
        sobrante = len(tool_output) - MAX_TOOL_OUTPUT_CHARS
        tool_output = f"{tool_output[:MAX_TOOL_OUTPUT_CHARS]}... [+{sobrante} chars]"

    db.add(
        ExecutionStep(
            session_id=session_id,
            turn=turn,
            iteration=iteration,
            tool_name=tool_name,
            # El input TAL CUAL lo mandó el modelo, antes de validarlo. Si
            # guardaras el ya normalizado, perderías justo la evidencia de qué
            # alucinó.
            tool_input=tool_input,
            tool_output=tool_output,
            is_error=is_error,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
    )
    await db.commit()


async def load_steps(
    db: AsyncSession, session_id: str, *, limit: int = 100, before_id: int | None = None
) -> list[ExecutionStep]:
    """La traza de una sesión, más nueva primero.

    Paginada por cursor (`before_id`) y no por `OFFSET`. Con offset, mientras
    alguien pagina, un paso nuevo al principio corre todo hacia atrás y la
    página 2 repite filas de la 1. Un cursor sobre una columna monótona no tiene
    ese problema, y además no obliga a la base a contar y descartar las filas
    que saltea.
    """
    consulta = (
        select(ExecutionStep)
        .where(ExecutionStep.session_id == session_id)
        .order_by(ExecutionStep.id.desc())
        .limit(limit)
    )
    if before_id is not None:
        consulta = consulta.where(ExecutionStep.id < before_id)

    return list((await db.execute(consulta)).scalars().all())


async def session_stats(db: AsyncSession, session_id: str) -> dict[str, Any]:
    """Resumen agregado de la traza de una sesión.

    Se calcula en la BASE, con `GROUP BY`, y no trayendo todas las filas a
    Python para contarlas. La diferencia no se nota con 10 pasos y se nota mucho
    con 10.000 — y la versión en Python tiene además el problema de que el
    resumen dejaría de ser exacto en cuanto la traza se pagine.
    """
    consulta = (
        select(
            ExecutionStep.tool_name,
            func.count().label("veces"),
            # `filter (where ...)` es el agregado condicional de SQL estándar:
            # cuenta sólo las filas que cumplen, en la misma pasada. Lo demás
            # sería una segunda query o un `sum(case when ...)`.
            func.count().filter(ExecutionStep.is_error).label("errores"),
            func.coalesce(func.sum(ExecutionStep.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(ExecutionStep.output_tokens), 0).label("output_tokens"),
        )
        .where(ExecutionStep.session_id == session_id)
        .group_by(ExecutionStep.tool_name)
        .order_by(func.count().desc())
    )
    filas = (await db.execute(consulta)).all()

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


async def _append_messages(
    db: AsyncSession,
    session_id: str,
    nuevos: list[MessageParam],
    turn: int | None,
) -> int:
    """Agrega mensajes al final del historial. NO commitea, NO toma el lock.

    Extraído para que `save_turn` y `pause_turn` compartan exactamente la misma
    lógica de posiciones. Duplicarla sería garantizar que un día se
    desincronicen, y el síntoma sería un historial desordenado — que es un
    request rechazado, no un detalle estético.

    Asume que quien llama ya tomó el lock sobre la sesión. Es un contrato
    implícito y por eso la función es privada: si la exportáramos, alguien la
    llamaría sin lock y la carrera volvería.
    """
    # Una sola query para las dos coordenadas. `coalesce` cubre el caso de la
    # sesión vacía, donde `max()` devuelve NULL y no 0: sin él, el primer turno
    # de cada sesión fallaría con un TypeError al sumarle 1 a None.
    consulta = select(
        func.coalesce(func.max(Message.position), -1),
        func.coalesce(func.max(Message.turn), 0),
    ).where(Message.session_id == session_id)
    ultima_posicion, ultimo_turno = (await db.execute(consulta)).one()

    # El turno puede venir dado: el loop lo reservó al empezar (con `next_turn`)
    # porque la traza de la Fase 4 lo necesita vuelta a vuelta, antes de que
    # exista este `save_turn`. Si no viene, se calcula acá.
    turno = turn if turn is not None else ultimo_turno + 1

    db.add_all(
        Message(
            session_id=session_id,
            turn=turno,
            position=ultima_posicion + offset,
            role=mensaje["role"],
            content=dump_blocks(mensaje["content"]),
        )
        for offset, mensaje in enumerate(nuevos, start=1)
    )
    return turno


async def pause_turn(
    db: AsyncSession,
    session_id: str,
    nuevos: list[MessageParam],
    *,
    turn: int,
    pendientes: list[tuple[str, str, dict[str, Any]]],
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> list[PendingApproval]:
    """Congela una corrida a mitad de camino, esperando una decisión humana.

    Guarda tres cosas y las guarda JUNTAS, en una transacción:

      1. El turno hasta acá — incluido el mensaje del assistant con los bloques
         `tool_use` que no se ejecutaron.
      2. Una fila por tool sensible pendiente.
      3. El estado de la sesión en `pending_approval`.

    Que sean atómicas es todo. Si el historial se guardara y los pendientes no,
    quedaría una sesión ACTIVA con un `tool_use` huérfano en su historial: el
    turno siguiente le mandaría a la API un request inválido y la conversación
    sería irrecuperable.

    ---

    Y acá hay que mirar de frente algo incómodo: **esto persiste un `tool_use`
    sin su `tool_result`**, que es justo lo que la Fase 1 dice que no se hace.

    No es una contradicción, es una precisión del invariante. La regla completa
    no era "el historial nunca tiene pares abiertos", sino:

        una sesión ACTIVA tiene un historial válido.

    Una sesión en `pending_approval` no es válida para mandarle a la API, y por
    eso rechaza mensajes nuevos con 409. El par se cierra cuando llega la
    decisión (Fase 6), y recién ahí la sesión vuelve a estar activa.

    La alternativa sería no persistir el turno y guardar el `messages` entero
    como JSON dentro del pendiente. Es peor: duplica el historial en dos lugares
    con formatos distintos, y el día que difieran no vas a saber cuál vale.
    """
    sesion = await get_session(db, session_id, for_update=True)

    turno = await _append_messages(db, session_id, nuevos, turn)

    ahora = datetime.now(UTC)
    aprobaciones = [
        PendingApproval(
            session_id=session_id,
            tool_use_id=tool_use_id,
            turn=turno,
            tool_name=tool_name,
            tool_input=tool_input,
            expires_at=ahora + TTL_APROBACION,
        )
        for tool_use_id, tool_name, tool_input in pendientes
    ]
    db.add_all(aprobaciones)

    # El estado es lo que hace cumplir la precisión del invariante de arriba.
    # Mientras diga esto, `mandar_mensaje` devuelve 409.
    sesion.status = SessionStatus.PENDING_APPROVAL

    # Los tokens ya gastados se cobran igual. El modelo trabajó: que la corrida
    # haya quedado en pausa no se lo devuelve nadie.
    sesion.input_tokens_used += input_tokens
    sesion.output_tokens_used += output_tokens

    await db.commit()
    return aprobaciones


async def pendientes_de(
    db: AsyncSession, session_id: str, *, only_pending: bool = True
) -> list[PendingApproval]:
    """Las aprobaciones de una sesión. Por default, sólo las que siguen abiertas."""
    consulta = select(PendingApproval).where(PendingApproval.session_id == session_id)
    if only_pending:
        consulta = consulta.where(PendingApproval.status == ApprovalStatus.PENDING)
    return list((await db.execute(consulta.order_by(PendingApproval.id))).scalars().all())


async def get_pending(db: AsyncSession, session_id: str, tool_use_id: str) -> PendingApproval:
    """Trae un pedido de aprobación concreto, o levanta.

    Se busca por `(session_id, tool_use_id)` y no por un id propio de la fila
    porque ése es el identificador que el cliente TIENE: se lo dimos en el 202,
    y es el mismo que va a llevar el `tool_result` cuando se arme. Un id
    distinto sería una correlación más que mantener sincronizada.
    """
    consulta = select(PendingApproval).where(
        PendingApproval.session_id == session_id,
        PendingApproval.tool_use_id == tool_use_id,
    )
    aprobacion = (await db.execute(consulta)).scalar_one_or_none()
    if aprobacion is None:
        raise ApprovalNotFoundError(tool_use_id)
    return aprobacion


async def resume_turn(
    db: AsyncSession,
    session_id: str,
    mensaje_resultados: MessageParam,
    *,
    turn: int,
) -> None:
    """Cierra la pausa: guarda los `tool_result` y reactiva la sesión.

    Es una unidad de trabajo propia y commitea sola, en vez de dejar todo para
    el `save_turn` del final del loop. La razón es concreta y vale entenderla.

    Cuando se aprueba, `cancel_order` corre y hace `flush` — el pedido queda
    cancelado en esta transacción. Si esperáramos al final del loop para
    commitear y el loop fallara (no converge, se cae la API), pasaría una de dos
    cosas malas: o se pierde la cancelación, o —peor— un `record_step` de una
    vuelta posterior la commitea sin su `tool_result`, y queda un pedido
    cancelado que el historial no registra.

    Commiteando acá, el efecto de la tool y la prueba de ese efecto entran
    juntos. Lo que venga después es otro problema, sobre una base consistente.

    NO toca `expires_at` ni el status del pendiente: eso ya lo hizo quien
    decidió, en esta misma transacción.
    """
    sesion = await get_session(db, session_id, for_update=True)

    await _append_messages(db, session_id, [mensaje_resultados], turn)

    # De vuelta a la normalidad: el historial volvió a tener todos sus pares
    # cerrados, así que la sesión ya puede recibir mensajes.
    sesion.status = SessionStatus.ACTIVE

    await db.commit()


async def save_turn(
    db: AsyncSession,
    session_id: str,
    nuevos: list[MessageParam],
    *,
    turn: int | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> int:
    """Persiste un turno COMPLETO en una sola transacción. Devuelve su número.

    Un turno es un mensaje del usuario y todo lo que el loop generó
    respondiéndolo: puede ser un mensaje o siete (`tool_use`, `tool_result`,
    `tool_use` otra vez, texto final).

    Que sea **una** transacción es el punto de la función, y el motivo es
    específico de este dominio: si commiteás mensaje por mensaje y el proceso
    muere en el medio, dejás persistido un `tool_use` sin su `tool_result`. Esa
    sesión no queda "incompleta": queda ROTA para siempre, porque cada request
    futuro le manda a la API un historial inválido. No hay reintento que la
    arregle; hay que editar filas a mano.

    Los tokens del turno se acumulan acá adentro, en la misma transacción, por
    la misma razón: un contador de gasto que puede desincronizarse del historial
    que lo causó no sirve para decidir nada (Fase 7).
    """
    # El lock se toma ANTES de leer las posiciones. Entre el `SELECT max(...)` y
    # el `INSERT` hay una ventana, y este lock es lo que la cierra.
    sesion = await get_session(db, session_id, for_update=True)

    turno = await _append_messages(db, session_id, nuevos, turn)

    # Acumular con `+=` en Python, y no con un `UPDATE ... SET x = x + n`, es
    # correcto acá SÓLO porque el `FOR UPDATE` de arriba serializó a los
    # escritores de esta sesión. Sin ese lock sería un clásico lost update: dos
    # transacciones leen 100, las dos escriben 150, y se perdió un turno de
    # gasto.
    sesion.input_tokens_used += input_tokens
    sesion.output_tokens_used += output_tokens

    await db.commit()
    return turno
