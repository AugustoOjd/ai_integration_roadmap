"""El estado del agente, como tablas.

Éste es el archivo que separa al mini 9 del mini 8. Allá el historial de una
corrida era una lista local de `run_agent` que moría con el request; acá es una
fila, y esa diferencia arrastra todo lo demás: memoria entre turnos, dueño de
los datos, traza auditable, pausa por aprobación y presupuesto.

Tres tablas, y la decisión de diseño está en por qué son tres:

    sessions         la conversación: dueño, presupuesto, estado
    messages         el historial TAL CUAL viaja a la API (input del modelo)
    execution_steps  qué hizo el agente y cuánto costó (output para humanos)

`messages` y `execution_steps` parecen la misma información y no lo son.
`messages` es **input del modelo** y su forma la dicta la Messages API: si le
cambiás un campo, cambiás lo que el modelo ve. `execution_steps` es **output
para humanos** y su forma la elegís vos: campos para auditar y para costear. Si
las mezclás en una tabla, cada necesidad de una te obliga a tocar la otra.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Raíz de todos los modelos.

    Vive acá y no en `db.py` a propósito: importar un modelo no tiene que
    arrastrar un engine ni una conexión. Los tests de la Fase 9 importan estas
    clases para armar objetos en memoria sin que haya un Postgres levantado.
    """


def _new_id(prefix: str) -> str:
    """Genera un id con prefijo legible: `s_3f9a...`, estilo Stripe.

    La alternativa obvia es un entero autoincremental, y tiene dos problemas
    acá. Uno es de seguridad: un id secuencial le dice a cualquiera cuántas
    sesiones tenés y le permite probar con el de al lado (la Fase 3 es
    exactamente sobre eso). El otro es operativo: cuando estés leyendo un log de
    la Fase 4 a las 3 AM, `s_3f9a` te dice qué tipo de cosa es y `4172` no.

    El costo es que un string de 34 chars indexa peor que un `bigint`. A esta
    escala no importa; a otra escala, la respuesta es UUIDv7 en una columna
    `UUID` nativa.
    """
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class SessionStatus(StrEnum):
    """Los estados en los que puede estar una conversación.

    `StrEnum` (3.11+) hace que el valor *sea* un string: se compara con `==` a
    un literal y se serializa solo en JSON, sin `.value` por todos lados.
    """

    # Acepta mensajes nuevos. Es el estado normal.
    ACTIVE = "active"

    # El loop se frenó esperando que un humano apruebe una tool sensible
    # (Fase 5). Una sesión acá RECHAZA mensajes nuevos con 409: primero se
    # resuelve lo pendiente, si no el historial queda con dos corridas
    # entrelazadas y ningún orden que tenga sentido.
    PENDING_APPROVAL = "pending_approval"

    # Se acabó el presupuesto de tokens (Fase 7). No es un error transitorio:
    # reintentar no lo arregla, hace falta subir el budget o abrir otra sesión.
    EXHAUSTED = "exhausted"


class OrderStatus(StrEnum):
    """Estados de un pedido. Sólo `PENDING` se puede cancelar (Fase 5)."""

    PENDING = "pending"
    SHIPPED = "shipped"
    CANCELLED = "cancelled"


class Order(Base):
    """Un pedido. El dato de negocio sobre el que operan las tools.

    Existe para darle a la Fase 3 algo real que proteger. El `user_id` de esta
    tabla es lo que una tool NO puede aceptar como argumento del modelo: si
    `get_my_orders` recibiera un `user_id` en su `input_schema`, cualquiera
    escribiría "mostrame los pedidos del usuario 7" y la tool obedecería.

    Y en la Fase 5 es lo que hace verificable la aprobación: que `cancel_order`
    se haya frenado no se comprueba leyendo la respuesta del agente, se comprueba
    mirando si el `status` de esta fila cambió.
    """

    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _new_id("o"))

    # El dueño. Todo acceso a esta tabla filtra por acá, y el valor sale del
    # contexto autenticado — nunca del prompt.
    user_id: Mapped[str] = mapped_column(String(64), index=True)

    item: Mapped[str] = mapped_column(String(200))

    # Dinero en CENTAVOS, como entero. Nunca en float: 0.1 + 0.2 no es 0.3 en
    # binario, y los redondeos se acumulan factura a factura hasta que la suma
    # no cuadra. La alternativa formal es `NUMERIC`; el entero de centavos es
    # más simple y no tiene el problema.
    amount_cents: Mapped[int] = mapped_column(Integer)

    has_discount: Mapped[bool] = mapped_column(default=False, server_default="false")

    status: Mapped[OrderStatus] = mapped_column(
        SAEnum(
            OrderStatus,
            native_enum=False,
            values_callable=lambda enum: [member.value for member in enum],
        ),
        default=OrderStatus.PENDING,
        server_default=OrderStatus.PENDING.value,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("amount_cents >= 0", name="ck_orders_amount_positive"),
    )


class ChatSession(Base):
    """Una conversación: quién es el dueño, cuánto puede gastar, cómo está.

    Se llama `ChatSession` y no `Session` por una colisión que se paga cara: en
    un archivo que persiste datos vas a tener importado el `Session` /
    `AsyncSession` de SQLAlchemy (la unidad de trabajo de la base) y el `Session`
    de FastAPI en las dependencias. Tres cosas distintas con el mismo nombre en
    el mismo módulo terminan en un import shadowing que el type checker no
    siempre atrapa.

    La tabla sí se llama `sessions`: el conflicto es del namespace de Python, no
    del de Postgres.
    """

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _new_id("s"))

    # El dueño. Es LA columna de la Fase 3: toda tool que toque datos del
    # usuario filtra por este valor, que sale del token de autenticación — nunca
    # del prompt, nunca del body.
    #
    # Indexada porque la query real de un backend no es "dame la sesión X" sino
    # "dame las sesiones de este usuario".
    user_id: Mapped[str] = mapped_column(String(64), index=True)

    # `native_enum=False` guarda un VARCHAR con un CHECK constraint en vez de un
    # tipo ENUM nativo de Postgres. Los enums nativos son rígidos: agregar un
    # valor es `ALTER TYPE ... ADD VALUE`, que hasta hace poco no podía correr
    # dentro de una transacción, y sacar un valor directamente no se puede. Con
    # VARCHAR + CHECK, cambiar el conjunto es un DDL común.
    #
    # `values_callable` hace que se guarde el VALOR del enum ("active") y no su
    # NOMBRE ("ACTIVE"), que es el default poco intuitivo de SQLAlchemy.
    status: Mapped[SessionStatus] = mapped_column(
        SAEnum(
            SessionStatus,
            native_enum=False,
            values_callable=lambda enum: [member.value for member in enum],
        ),
        default=SessionStatus.ACTIVE,
        server_default=SessionStatus.ACTIVE.value,
    )

    # ---- Presupuesto (Fase 7) --------------------------------------------

    # El tope de esta sesión en particular. Se copia del default de config al
    # crearla, en vez de leerse de config en cada chequeo: si mañana bajás el
    # default, las sesiones abiertas no cambian de reglas a mitad de camino.
    budget_tokens: Mapped[int] = mapped_column(Integer)

    # Input y output se acumulan POR SEPARADO, no en un solo contador, porque
    # tienen precios distintos (con Haiku 4.5, $1 y $5 por millón). Un único
    # `tokens_used` no se puede convertir a dinero sin inventar un promedio.
    input_tokens_used: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    output_tokens_used: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    # ---- Timestamps -------------------------------------------------------

    # `timezone=True` → TIMESTAMPTZ. Un TIMESTAMP sin zona es una fecha sin
    # significado: dos procesos en zonas distintas escriben valores que no se
    # pueden comparar. Postgres normaliza a UTC y devuelve un datetime aware.
    #
    # `server_default=func.now()` hace que el reloj sea el de la BASE, no el de
    # la app. Con varios workers (y con Celery en PROJECT 2) los relojes de los
    # procesos no coinciden; el de la base es uno solo.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # ---- Relaciones -------------------------------------------------------

    # `lazy="raise"` es la defensa que hace vivible a SQLAlchemy async. Por
    # default, tocar `session.messages` sin haberlo cargado dispara una query
    # implícita; en async eso explota con un `MissingGreenlet` que no dice nada
    # sobre la causa. Con `raise`, el error es explícito y en el lugar correcto:
    # "cargá esto a propósito, con un `selectinload`".
    #
    # `cascade="all, delete-orphan"` + `passive_deletes=True`: la cascada real
    # la hace Postgres con el ON DELETE del foreign key (una sentencia), y
    # SQLAlchemy no intenta borrar fila por fila desde Python.
    messages: Mapped[list["Message"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
        order_by="Message.position",
    )
    steps: Mapped[list["ExecutionStep"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
        order_by="ExecutionStep.id",
    )

    __table_args__ = (
        # Invariantes que la base garantiza aunque tu código tenga un bug. Un
        # presupuesto negativo o un contador que baja son estados imposibles:
        # mejor que el INSERT falle a que la sesión quede envenenada.
        CheckConstraint("budget_tokens > 0", name="ck_sessions_budget_positive"),
        CheckConstraint("input_tokens_used >= 0", name="ck_sessions_input_used_positive"),
        CheckConstraint("output_tokens_used >= 0", name="ck_sessions_output_used_positive"),
    )


class Message(Base):
    """Un mensaje del historial, exactamente como viaja a la Messages API.

    La tentación de esta tabla es guardar el texto legible. No se puede: el
    `content` de un mensaje es una LISTA DE BLOQUES (`text`, `tool_use`,
    `tool_result`), y los bloques de tools son los que sostienen la correlación
    por `tool_use_id`. Si guardás sólo el texto, en el turno siguiente le mandás
    a la API un historial donde el `tool_result` no tiene su `tool_use`, y te
    contesta:

        messages.N: tool_use ids were found without tool_result blocks

    Por eso la regla de la Fase 1: **el historial se persiste tal cual viaja.**
    La vista legible para un humano es una proyección (Fase 4), no el dato.
    """

    __tablename__ = "messages"

    # Acá sí un entero: estas filas son muchas (varias por turno), nadie las
    # nombra desde afuera y nunca aparecen en una URL. El razonamiento del
    # `_new_id` no aplica.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # `ondelete="CASCADE"` va en la BASE, no sólo en el ORM: si alguna vez
    # borrás una sesión con un DELETE a mano, los mensajes se van con ella en
    # vez de dejar filas huérfanas apuntando a nada.
    #
    # Sin `index=True`: el UniqueConstraint de abajo ya crea un índice sobre
    # (session_id, position), y un índice compuesto sirve para las queries que
    # filtran por su PREFIJO — o sea, también para "todos los mensajes de esta
    # sesión". Agregar otro índice sobre `session_id` solo sería una segunda
    # estructura que Postgres mantiene en cada INSERT sin usarla nunca.
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"))

    # A qué turno de conversación pertenece este mensaje. Un turno es UN mensaje
    # del usuario y todo lo que el loop generó respondiéndolo: puede ser un solo
    # mensaje o siete. Se guarda porque es la unidad que importa después:
    #   - Fase 1: la transacción es por turno.
    #   - Fase 8: el recorte de contexto tira turnos completos, nunca mensajes
    #     sueltos, justamente para no partir un par tool_use/tool_result.
    turn: Mapped[int] = mapped_column(Integer)

    # El orden dentro de la sesión, explícito. NO alcanza con ordenar por `id`
    # ni por `created_at`: el id autoincremental depende de una secuencia que
    # puede entregar valores fuera de orden entre transacciones concurrentes, y
    # dos mensajes del mismo turno se insertan en el mismo milisegundo. El orden
    # del historial no es un detalle estético — un historial desordenado es un
    # request inválido.
    position: Mapped[int] = mapped_column(Integer)

    # "user" | "assistant". La Messages API no tiene rol "system" en `messages`
    # (el system prompt es un parámetro aparte), así que sólo hay dos valores.
    #
    # Contraintuitivo pero correcto: los `tool_result` que escribís VOS van con
    # rol "user". Desde la perspectiva del modelo, vos sos el usuario.
    role: Mapped[str] = mapped_column(String(16))

    # JSONB y no `text`, por dos razones. La obvia: es una lista de objetos, no
    # un string. La que se agradece después: JSONB permite consultar adentro
    # ("dame los mensajes que contienen un tool_use de cancel_order") sin
    # levantar todo a Python.
    #
    # JSONB y no JSON: JSON guarda el texto crudo, JSONB guarda una forma
    # binaria parseada. JSONB es lo que se indexa y lo que se consulta; el único
    # precio es que no preserva el orden de las claves ni los espacios, que acá
    # no significan nada.
    content: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    session: Mapped[ChatSession] = relationship(back_populates="messages", lazy="raise")

    __table_args__ = (
        # El invariante del historial: dentro de una sesión no puede haber dos
        # mensajes en la misma posición. Esto es lo que convierte "el orden" de
        # una convención de tu código en una garantía de la base.
        #
        # Y de yapa resuelve la performance: un UNIQUE en Postgres se implementa
        # COMO un índice btree, así que esta línea también es el índice de la
        # query que corre en cada request —"los mensajes de esta sesión, en
        # orden"— y Postgres los devuelve ya ordenados, sin sort.
        UniqueConstraint("session_id", "position", name="uq_messages_session_position"),
        CheckConstraint("role in ('user', 'assistant')", name="ck_messages_role"),
    )


class ApprovalStatus(StrEnum):
    """El ciclo de vida de un pedido de aprobación."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    # Se venció sin que nadie decidiera. No es lo mismo que rechazado: nadie
    # dijo que no, simplemente ya no es razonable ejecutarlo.
    EXPIRED = "expired"


class PendingApproval(Base):
    """Una tool sensible esperando el sí o el no de un humano.

    Ésta es la tabla que convierte una pausa en algo real. Un loop pausado es
    estado que sobrevive al request: no se puede tener el `for` corriendo con un
    `await` esperando a una persona que quizás conteste mañana, porque el worker
    se reinicia, el deploy pasa y la conexión se cae.

    Guardado acá, retomar deja de ser "seguir" y pasa a ser **reconstruir**: un
    request nuevo levanta el historial, le agrega el `tool_result` que faltaba, y
    sigue el loop desde ahí. Que es, casualmente, el mismo problema que va a
    plantear Celery en PROJECT 2.
    """

    __tablename__ = "pending_approvals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"))

    # El id del bloque `tool_use` que quedó sin ejecutar. Es LA clave de todo:
    # el historial ya tiene ese `tool_use` persistido, y cuando la decisión
    # llegue, el `tool_result` que se arme tiene que llevar este mismo id o la
    # API rechaza el request.
    tool_use_id: Mapped[str] = mapped_column(String(64))

    # En qué turno quedó pausada la corrida, para saber dónde retomar.
    turn: Mapped[int] = mapped_column(Integer)

    tool_name: Mapped[str] = mapped_column(String(64))
    # Los argumentos que el modelo propuso. Se guardan para poder EJECUTARLOS
    # después —el request de aprobación no los manda de nuevo— y para que quien
    # aprueba pueda ver exactamente qué está aprobando.
    tool_input: Mapped[dict[str, Any]] = mapped_column(JSONB)

    status: Mapped[ApprovalStatus] = mapped_column(
        SAEnum(
            ApprovalStatus,
            native_enum=False,
            values_callable=lambda enum: [member.value for member in enum],
        ),
        default=ApprovalStatus.PENDING,
        server_default=ApprovalStatus.PENDING.value,
    )

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # Cuándo se decidió. NULL mientras está pendiente — el propio campo dice si
    # ya pasó por una decisión, sin tener que interpretar el status.
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        # El candado de idempotencia. Dos `POST` de aprobación con el mismo
        # `tool_use_id` no pueden crear dos pendientes ni ejecutar la tool dos
        # veces: hay una sola fila, y su `status` es el que dice si ya se
        # decidió.
        UniqueConstraint("session_id", "tool_use_id", name="uq_approval_session_tool_use"),
        # La query de la Fase 6: "¿queda algo pendiente en esta sesión?".
        Index("ix_approvals_session_status", "session_id", "status"),
    )


class ExecutionStep(Base):
    """Una tool ejecutada: qué se pidió, qué devolvió, cuánto costó.

    Es la traza de la Fase 4, y existe porque `print` sirve mientras mirás una
    terminal. Acá el agente toca datos de un usuario y ejecuta acciones a su
    nombre: la pregunta "¿por qué el agente hizo *eso*?" hay que poder
    contestarla tres días después, para una sesión concreta, sin grep.

    Esta tabla NO se le manda al modelo. Es para vos.
    """

    __tablename__ = "execution_steps"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # Sin `index=True`, por lo mismo que en `messages`: el índice compuesto de
    # `__table_args__` empieza por `session_id` y ya cubre este filtro.
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"))

    # Las dos coordenadas que ubican un paso: en qué turno de la conversación, y
    # en qué vuelta del loop dentro de ese turno. Juntas contestan "el agente
    # llamó a esta tool en la segunda vuelta del tercer mensaje".
    turn: Mapped[int] = mapped_column(Integer)
    iteration: Mapped[int] = mapped_column(Integer)

    tool_name: Mapped[str] = mapped_column(String(64), index=True)

    # El input TAL CUAL lo mandó el modelo, antes de tu validación. Es lo que
    # querés ver cuando una tool se comportó raro: si guardás el input ya
    # normalizado, perdés justo la evidencia de qué alucinó.
    tool_input: Mapped[dict[str, Any]] = mapped_column(JSONB)

    # El output, RECORTADO antes de guardarse. Una tool que devuelve 200 KB te
    # infla esta tabla igual que te infla el contexto; y a diferencia del
    # contexto, acá nadie lo va a leer entero.
    #
    # Nullable porque un paso puede no haber llegado a producir output (la tool
    # falló, o quedó pendiente de aprobación en la Fase 5).
    tool_output: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Una tool que falla no es un error del request: se le devuelve al modelo
    # como `tool_result` con `is_error`, y el modelo reacciona (reintenta con
    # otros argumentos, o le avisa al usuario). Pero sí es algo que querés poder
    # contar: "qué porcentaje de llamadas a `search` falla" es una métrica.
    is_error: Mapped[bool] = mapped_column(default=False, server_default="false")

    # Cuánto tardó la TOOL, no la llamada al modelo. Es el número que te dice si
    # el agente está lento por el LLM o por tu propia integración.
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # El `usage` de la llamada al modelo de esa vuelta. Nullable porque no todo
    # paso tiene una llamada asociada, y porque son datos del proveedor: si un
    # día no vienen, la traza sigue siendo válida.
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    session: Mapped[ChatSession] = relationship(back_populates="steps", lazy="raise")

    __table_args__ = (
        # La consulta de `GET /sessions/{id}/log`: la traza de una sesión, más
        # nueva primero.
        #
        # El índice se declara ASC aunque la query ordene DESC, y está bien:
        # Postgres puede recorrer un btree hacia atrás. Un índice DESC explícito
        # sólo hace falta cuando ordenás por VARIAS columnas en direcciones
        # distintas, que no es el caso.
        Index("ix_steps_session_created", "session_id", "created_at"),
    )
