"""El estado del agente, como tablas.

    sessions          la conversación: dueño, presupuesto, estado
    messages          el historial tal cual viaja a la API (input del modelo)
    pending_approvals una tool sensible esperando el sí de un humano
    execution_steps   qué hizo el agente y cuánto costó (output para humanos)
    orders            el dato de negocio sobre el que operan las tools

`messages` y `execution_steps` parecen lo mismo y no lo son: la forma de
`messages` la dicta la Messages API, la de `execution_steps` la elegís vos.
Juntas en una tabla, cada necesidad de una obliga a tocar la otra.
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

    Vive acá y no en db.py: importar un modelo no arrastra un engine, así que los
    tests pueden armar objetos sin Postgres levantado.
    """


def _new_id(prefix: str) -> str:
    """Id con prefijo legible: `s_3f9a...`, estilo Stripe.

    Un autoincremental delataría cuántas filas hay y permitiría probar con el de
    al lado. Además, en un log a las 3 AM `s_3f9a` dice qué tipo de cosa es.
    """
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


# StrEnum (3.11+) hace que el valor SEA un string: se compara con == a un literal
# y se serializa solo en JSON, sin .value por todos lados.
class SessionStatus(StrEnum):
    ACTIVE = "active"
    # El loop se frenó esperando una aprobación. Rechaza mensajes nuevos con 409:
    # si no, el historial queda con dos corridas entrelazadas.
    PENDING_APPROVAL = "pending_approval"
    # Sin presupuesto. Reintentar no lo arregla.
    EXHAUSTED = "exhausted"


class OrderStatus(StrEnum):
    PENDING = "pending"
    SHIPPED = "shipped"
    CANCELLED = "cancelled"


class Order(Base):
    """Un pedido: el dato real que las tools leen y modifican.

    Hace verificable la aprobación — que `cancel_order` se haya frenado no se
    comprueba leyendo la respuesta del agente, se comprueba mirando este `status`.
    """

    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _new_id("o"))

    # El dueño. Todo acceso filtra por acá, con el valor del contexto autenticado
    # y nunca del prompt.
    user_id: Mapped[str] = mapped_column(String(64), index=True)

    item: Mapped[str] = mapped_column(String(200))

    # Dinero en centavos, como entero: en float, 0.1 + 0.2 no es 0.3 y los
    # redondeos se acumulan hasta que la suma no cuadra.
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

    Se llama ChatSession y no Session para no colisionar con la Session de
    SQLAlchemy, que está importada en todo archivo que persista datos. La tabla
    sí se llama `sessions`: el conflicto es del namespace de Python.
    """

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _new_id("s"))

    # Indexada porque la query real no es "dame la sesión X" sino "dame las
    # sesiones de este usuario".
    user_id: Mapped[str] = mapped_column(String(64), index=True)

    # native_enum=False guarda un VARCHAR con CHECK en vez de un ENUM nativo:
    # agregar o sacar un valor pasa a ser un DDL común en vez de un ALTER TYPE.
    # values_callable guarda el valor ("active") y no el nombre ("ACTIVE").
    status: Mapped[SessionStatus] = mapped_column(
        SAEnum(
            SessionStatus,
            native_enum=False,
            values_callable=lambda enum: [member.value for member in enum],
        ),
        default=SessionStatus.ACTIVE,
        server_default=SessionStatus.ACTIVE.value,
    )

    # Se copia del default de config al crear la sesión: si mañana baja el
    # default, las sesiones abiertas no cambian de reglas a mitad de camino.
    budget_tokens: Mapped[int] = mapped_column(Integer)

    # Input y output separados porque tienen precios distintos. Un solo contador
    # no se puede convertir a dinero sin inventar un promedio.
    input_tokens_used: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    output_tokens_used: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    # timezone=True → TIMESTAMPTZ: sin zona, dos procesos escriben valores que no
    # se pueden comparar. server_default=func.now() usa el reloj de la base, que
    # es uno solo aunque haya varios procesos.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # lazy="raise": tocar la relación sin haberla cargado tira un error explícito
    # en vez de disparar una query implícita (N+1, o DetachedInstanceError si la
    # sesión ya cerró). Se carga a propósito con selectinload.
    # cascade + passive_deletes: el borrado lo hace el ON DELETE de Postgres en
    # una sentencia, no SQLAlchemy fila por fila.
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
        # Estados imposibles que la base rechaza aunque el código tenga un bug.
        CheckConstraint("budget_tokens > 0", name="ck_sessions_budget_positive"),
        CheckConstraint("input_tokens_used >= 0", name="ck_sessions_input_used_positive"),
        CheckConstraint("output_tokens_used >= 0", name="ck_sessions_output_used_positive"),
    )


class Message(Base):
    """Un mensaje del historial, exactamente como viaja a la Messages API.

    No se puede guardar sólo el texto legible: el content es una lista de bloques
    (text, tool_use, tool_result) y los de tools sostienen la correlación por
    tool_use_id. Sin ellos, el request siguiente falla con:

        messages.N: tool_use ids were found without tool_result blocks
    """

    __tablename__ = "messages"

    # Entero y no _new_id: son muchas filas, nadie las nombra desde afuera y
    # nunca aparecen en una URL.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # ondelete en la base y no sólo en el ORM: un DELETE a mano se lleva los
    # mensajes en vez de dejar filas huérfanas.
    # Sin index=True: el UniqueConstraint de abajo ya crea un índice que empieza
    # por session_id, y un compuesto sirve para las queries que filtran por su
    # prefijo.
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"))

    # Un turno es un mensaje del usuario y todo lo que el loop generó
    # respondiéndolo. Es la unidad de la transacción y la del recorte de contexto,
    # que tira turnos completos para no partir un par tool_use/tool_result.
    turn: Mapped[int] = mapped_column(Integer)

    # El orden explícito. No alcanza con ordenar por id ni por created_at: la
    # secuencia puede entregar valores fuera de orden entre transacciones
    # concurrentes, y dos mensajes del mismo turno caen en el mismo milisegundo.
    position: Mapped[int] = mapped_column(Integer)

    # "user" | "assistant". No hay rol "system" en messages (el system prompt es
    # un parámetro aparte). Los tool_result que escribís vos van con rol "user":
    # desde la perspectiva del modelo, vos sos el usuario.
    role: Mapped[str] = mapped_column(String(16))

    # JSONB y no text porque es una lista de objetos, y JSONB y no JSON porque se
    # puede consultar adentro ("mensajes con un tool_use de cancel_order") sin
    # levantar todo a Python.
    content: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    session: Mapped[ChatSession] = relationship(back_populates="messages", lazy="raise")

    __table_args__ = (
        # El orden del historial pasa de convención del código a garantía de la
        # base. Y como un UNIQUE en Postgres se implementa como un btree, esta
        # línea es además el índice de "los mensajes de esta sesión, en orden",
        # que vuelven ya ordenados y sin sort.
        UniqueConstraint("session_id", "position", name="uq_messages_session_position"),
        CheckConstraint("role in ('user', 'assistant')", name="ck_messages_role"),
    )


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    # Venció sin que nadie decidiera. Distinto de rechazado: nadie dijo que no.
    EXPIRED = "expired"


class PendingApproval(Base):
    """Una tool sensible esperando el sí o el no de un humano.

    Convierte la pausa en estado que sobrevive al request: no se puede tener el
    loop corriendo esperando a alguien que quizás conteste mañana, porque el
    proceso se reinicia. Persistido acá, retomar es reconstruir la corrida desde
    la base.
    """

    __tablename__ = "pending_approvals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"))

    # El id del bloque tool_use que quedó sin ejecutar. El historial ya lo tiene
    # persistido, así que el tool_result que se arme después tiene que llevar este
    # mismo id o la API rechaza el request.
    tool_use_id: Mapped[str] = mapped_column(String(64))

    # En qué turno quedó pausada la corrida, para saber dónde retomar.
    turn: Mapped[int] = mapped_column(Integer)

    tool_name: Mapped[str] = mapped_column(String(64))

    # Los argumentos que propuso el modelo. Se guardan para poder ejecutarlos
    # después —el request de aprobación no los manda de nuevo— y para que quien
    # aprueba vea qué está aprobando.
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

    # NULL mientras está pendiente: el campo dice si ya hubo decisión sin tener
    # que interpretar el status.
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        # El candado de idempotencia: dos aprobaciones del mismo tool_use_id no
        # pueden crear dos pendientes ni ejecutar la tool dos veces.
        UniqueConstraint("session_id", "tool_use_id", name="uq_approval_session_tool_use"),
        # "¿queda algo pendiente en esta sesión?"
        Index("ix_approvals_session_status", "session_id", "status"),
    )


class ExecutionStep(Base):
    """Una tool ejecutada: qué se pidió, qué devolvió, cuánto costó.

    Contesta "¿por qué el agente hizo eso?" tres días después, para una sesión
    concreta y sin grep. No se le manda al modelo: es para vos.
    """

    __tablename__ = "execution_steps"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # Sin index=True: el índice compuesto de __table_args__ empieza por
    # session_id y ya cubre este filtro.
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"))

    # Las dos coordenadas que ubican un paso: en qué turno de la conversación y en
    # qué vuelta del loop dentro de ese turno.
    turn: Mapped[int] = mapped_column(Integer)
    iteration: Mapped[int] = mapped_column(Integer)

    tool_name: Mapped[str] = mapped_column(String(64), index=True)

    # El input tal cual lo mandó el modelo, antes de validarlo: guardarlo ya
    # normalizado pierde justo la evidencia de qué alucinó.
    tool_input: Mapped[dict[str, Any]] = mapped_column(JSONB)

    # Recortado antes de guardarse: una tool que devuelve 200 KB infla esta tabla
    # y nadie la va a leer entera. Nullable porque el paso puede no haber llegado
    # a producir output.
    tool_output: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Una tool que falla no es un error del request: se le devuelve al modelo como
    # tool_result con is_error. Pero sí es algo que querés poder contar.
    is_error: Mapped[bool] = mapped_column(default=False, server_default="false")

    # Cuánto tardó la tool, no la llamada al modelo: es el número que dice si el
    # agente está lento por el LLM o por tu integración.
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # El usage de la llamada al modelo de esa vuelta. Nullable porque no todo paso
    # tiene una llamada asociada.
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    session: Mapped[ChatSession] = relationship(back_populates="steps", lazy="raise")

    __table_args__ = (
        # "la traza de esta sesión, más nueva primero". Se declara ASC aunque la
        # query ordene DESC: Postgres recorre un btree hacia atrás sin problema.
        Index("ix_steps_session_created", "session_id", "created_at"),
    )
