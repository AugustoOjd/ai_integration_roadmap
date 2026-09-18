"""El estado del agente, como tablas.

    conversations     el hilo: dueño, presupuesto, estado         (dura para siempre)
    tasks             una ejecución del agente sobre ese hilo     (dura minutos)
    messages          el historial tal cual viaja a la API (input del modelo)
    pending_approvals una tool sensible esperando el sí de un humano
    execution_steps   qué hizo el agente y cuánto costó (output para humanos)
    orders            el dato de negocio sobre el que operan las tools

Una conversación tiene muchas tareas, y la distinción es la que decide dónde
cuelga cada cosa: el historial pertenece a la **conversación**, porque la tarea 2
necesita lo que dejó la 1; la traza pertenece a la **tarea**, porque "¿cómo va
esto que pedí?" se pregunta de una ejecución y no de un hilo.

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
    """Id con prefijo legible: `c_3f9a...`, `t_8b2c...`, estilo Stripe.

    Un autoincremental delataría cuántas filas hay y permitiría probar con el de
    al lado. Además, en un log a las 3 AM `c_3f9a` dice de qué tabla es — y con
    conversaciones y tareas conviviendo, eso deja de ser un lujo.
    """
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


# StrEnum (3.11+) hace que el valor SEA un string: se compara con == a un literal
# y se serializa solo en JSON, sin .value por todos lados.
class ConversationStatus(StrEnum):
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


class Conversation(Base):
    """El hilo: quién es el dueño, cuánto puede gastar, cómo está.

    Vive para siempre y acumula el historial. Lo que dura minutos es la `Task`:
    una ejecución del agente sobre esta conversación. Confundir las dos es el
    error que cuesta un refactor — el historial no puede colgar de la tarea,
    porque la tarea 2 necesita lo que dejó la 1.

    De paso, el nombre no colisiona con la `Session` de SQLAlchemy, que está
    importada en todo archivo que persista datos.
    """

    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _new_id("c"))

    # Indexada porque la query real no es "dame la conversación X" sino "dame las
    # conversaciones de este usuario".
    user_id: Mapped[str] = mapped_column(String(64), index=True)

    # native_enum=False guarda un VARCHAR con CHECK en vez de un ENUM nativo:
    # agregar o sacar un valor pasa a ser un DDL común en vez de un ALTER TYPE.
    # values_callable guarda el valor ("active") y no el nombre ("ACTIVE").
    status: Mapped[ConversationStatus] = mapped_column(
        SAEnum(
            ConversationStatus,
            native_enum=False,
            values_callable=lambda enum: [member.value for member in enum],
        ),
        default=ConversationStatus.ACTIVE,
        server_default=ConversationStatus.ACTIVE.value,
    )

    # Se copia del default de config al crear la conversación: si mañana baja el
    # default, las conversaciones abiertas no cambian de reglas a mitad de camino.
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
    # conversación ya cerró). Se carga a propósito con selectinload.
    # cascade + passive_deletes: el borrado lo hace el ON DELETE de Postgres en
    # una sentencia, no SQLAlchemy fila por fila.
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
        order_by="Message.position",
    )
    steps: Mapped[list["ExecutionStep"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
        order_by="ExecutionStep.id",
    )
    tasks: Mapped[list["Task"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
        order_by="Task.created_at",
    )

    __table_args__ = (
        # Estados imposibles que la base rechaza aunque el código tenga un bug.
        CheckConstraint("budget_tokens > 0", name="ck_conversations_budget_positive"),
        CheckConstraint(
            "input_tokens_used >= 0", name="ck_conversations_input_used_positive"
        ),
        CheckConstraint(
            "output_tokens_used >= 0", name="ck_conversations_output_used_positive"
        ),
    )


class TaskStatus(StrEnum):
    """El ciclo de vida de una ejecución.

    Las transiciones válidas son pocas y van en una sola dirección:

        pending ──> running ──> success
                           ├──> failed
                           └──> pending_approval

    Falta `cancelled`, que llega con la cancelación cooperativa. Agregarlo va a
    ser un DDL común y no un `ALTER TYPE`, porque el enum se guarda como VARCHAR.

    Las transiciones válidas no están acá sino en `app/tasks/state.py`: el enum
    dice qué valores existen, la máquina dice cómo se llega a cada uno.
    """

    # Creada, todavía no arrancó. Con un worker de por medio es el estado que el
    # usuario ve durante varios segundos.
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    # Detenida esperando que un humano autorice una tool sensible. No es un
    # fallo y no es un final: es una pausa con estado propio.
    PENDING_APPROVAL = "pending_approval"
    # La pidió cancelar el usuario. Distinto de `failed`: una la pidió alguien, la
    # otra salió mal. Mezclarlas arruina cualquier métrica de tasa de error.
    CANCELLED = "cancelled"


class Task(Base):
    """Una ejecución del agente sobre una conversación.

    Dura minutos; la conversación dura para siempre. Y el estado de esta fila
    **es** la respuesta: cuando el request devuelve un id en vez de un resultado,
    no hay otro canal por donde contar que algo falló, se pausó o terminó.
    """

    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _new_id("t"))

    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )

    # El pedido, tal cual llegó.
    #
    # Vive acá y no sólo como un `Message` porque la tarea existe ANTES de
    # correr: en el momento de crearla no hay ningún mensaje todavía. El Message
    # aparece cuando el turno se persiste, y es el mismo texto — pero uno es la
    # intención y el otro es el historial.
    prompt: Mapped[str] = mapped_column(Text)

    status: Mapped[TaskStatus] = mapped_column(
        SAEnum(
            TaskStatus,
            native_enum=False,
            values_callable=lambda enum: [member.value for member in enum],
        ),
        default=TaskStatus.PENDING,
        server_default=TaskStatus.PENDING.value,
    )

    # Lo que devolvió el agente: answer, iterations, tools_used, usage. JSONB y no
    # columnas sueltas porque es la respuesta de una corrida, no datos que se
    # consulten con un WHERE.
    #
    # NULL mientras no terminó. El propio campo dice si hay resultado.
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Por qué falló, para el humano que mira. NULL si no falló.
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Cuántos reintentos se consumieron. Celery lo sabe, pero en un backend que
    # vence en una hora y que no es la fuente de verdad: acá se puede consultar
    # con un `group by` junto al resto del estado.
    retries: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    # La última señal de vida de quien la está corriendo. Se actualiza vuelta a
    # vuelta del loop.
    #
    # Existe porque un worker muerto no puede decir que se murió: alguien de
    # afuera tiene que notar que dejó de latir. NULL mientras nadie la tomó.
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # La señal de cancelación. Es un flag y no un estado porque son dos cosas:
    # "alguien la quiere frenar" y "ya se frenó". Entre una y otra pasa lo que
    # tarde el loop en llegar a un punto seguro.
    #
    # Vive en la base y no en memoria porque quien cancela (un request HTTP) y
    # quien obedece (un worker) son procesos distintos. Es el único canal que
    # tienen.
    cancel_requested: Mapped[bool] = mapped_column(default=False, server_default="false")

    # No hay `user_id` acá: sale de la conversación. Duplicarlo sería una segunda
    # fuente de verdad sobre de quién es la corrida, y ésa es exactamente la
    # columna que no puede discrepar.

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # NULL hasta que un worker la toma, y hasta que termina. La diferencia entre
    # created y started es lo que esperó en la cola; entre started y finished, lo
    # que tardó el agente. Son dos métricas distintas y por eso son dos columnas.
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    conversation: Mapped[Conversation] = relationship(back_populates="tasks", lazy="raise")

    __table_args__ = (
        # "las tareas de esta conversación, más nueva primero"
        Index("ix_tasks_conversation_created", "conversation_id", "created_at"),
        # "qué está corriendo ahora": el filtro de GET /tasks?status=running y,
        # más adelante, el que usa el reaper para encontrar tareas colgadas.
        Index("ix_tasks_status", "status"),
    )


class ToolExecutionStatus(StrEnum):
    # Se reservó y todavía no volvió. Si esto sobrevive a un reinicio, hay un
    # efecto del que no sabemos si ocurrió.
    IN_FLIGHT = "in_flight"
    DONE = "done"


class ToolExecution(Base):
    """El candado de idempotencia de una tool con efectos.

    La clave primaria es el `tool_use_id` que mandó el modelo, y ésa es toda la
    idea: viene del historial persistido, así que es **estable entre reintentos**.
    Un `uuid4()` generado al ejecutar sería distinto cada vez y no serviría de
    candado.

    Vive en la MISMA transacción que la tool, y eso hace que para una tool cuyo
    efecto está en esta base —`cancel_order`— la idempotencia sea perfecta: o
    commitean las dos cosas o ninguna. Para una tool cuyo efecto sale afuera
    (un mail, un cobro) eso no alcanza, y `in_flight` es el estado que nombra esa
    ventana.
    """

    __tablename__ = "tool_executions"

    tool_use_id: Mapped[str] = mapped_column(String(64), primary_key=True)

    # Para auditar y para que el borrado de una conversación se lleve esto.
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    tool_name: Mapped[str] = mapped_column(String(64))

    status: Mapped[ToolExecutionStatus] = mapped_column(
        SAEnum(
            ToolExecutionStatus,
            native_enum=False,
            values_callable=lambda enum: [member.value for member in enum],
        ),
        default=ToolExecutionStatus.IN_FLIGHT,
        server_default=ToolExecutionStatus.IN_FLIGHT.value,
    )

    # Lo que devolvió la tool, para poder responder lo MISMO en la segunda
    # ejecución. Sin esto, la reejecución no repite el efecto pero sí le cambia
    # la respuesta al modelo, y el historial deja de reproducirse igual.
    result: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_tool_exec_conversation", "conversation_id"),
    )


class UserBudget(Base):
    """Cuánto puede gastar un usuario en una ventana de tiempo.

    El presupuesto de la conversación acota **un hilo**: protege contra una
    conversación que se desbocó. Éste acota **a la persona**, y cruza
    conversaciones, tareas y workers: protege la factura.

    Son dos cosas distintas y por eso conviven. Un usuario con veinte
    conversaciones de presupuesto sano puede gastar veinte veces más de lo que
    pensabas.

    La ventana es **fija**, no deslizante: se trunca a la hora. Una deslizante
    ("los últimos 60 minutos") es más justa y obliga a sumar sobre un histórico
    en cada chequeo; la fija es una fila y un `where`. A esta escala la fija
    alcanza, y el precio conocido es el borde: alguien puede gastar el límite a
    las 10:59 y otra vez a las 11:00.
    """

    __tablename__ = "user_budgets"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)

    # Truncada a la hora. Es parte de la clave: una fila por usuario y ventana.
    window_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True
    )

    # Se copia de config al crear la fila, igual que el de la conversación: si
    # mañana baja el default, la ventana en curso no cambia de reglas.
    tokens_limit: Mapped[int] = mapped_column(Integer)

    # Apartados para llamadas que todavía no volvieron. Sube al reservar y baja
    # al liquidar; en reposo tiene que ser 0.
    tokens_reserved: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    # Gastados de verdad, con el `usage` de la respuesta.
    tokens_used: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("tokens_reserved >= 0", name="ck_budget_reserved_positive"),
        CheckConstraint("tokens_used >= 0", name="ck_budget_used_positive"),
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
    # por conversation_id, y un compuesto sirve para las queries que filtran por su
    # prefijo.
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )

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

    conversation: Mapped[Conversation] = relationship(back_populates="messages", lazy="raise")

    __table_args__ = (
        # El orden del historial pasa de convención del código a garantía de la
        # base. Y como un UNIQUE en Postgres se implementa como un btree, esta
        # línea es además el índice de "los mensajes de esta conversación, en orden",
        # que vuelven ya ordenados y sin sort.
        UniqueConstraint(
            "conversation_id", "position", name="uq_messages_conversation_position"
        ),
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

    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )

    # De qué ejecución salió. Nullable porque el endpoint sincrónico de
    # `/messages` puede pausar sin que haya una tarea detrás.
    #
    # Sin esta columna se podría llegar a la tarea por la conversación —sólo una
    # puede estar pausada por vez, porque una conversación pausada rechaza tareas
    # nuevas— pero sería una deducción, y las deducciones se rompen el día que
    # alguien relaja esa regla.
    task_id: Mapped[str | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True
    )

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
        UniqueConstraint(
            "conversation_id", "tool_use_id", name="uq_approval_conversation_tool_use"
        ),
        # "¿queda algo pendiente en esta conversación?"
        Index("ix_approvals_conversation_status", "conversation_id", "status"),
    )


class ExecutionStep(Base):
    """Una tool ejecutada: qué se pidió, qué devolvió, cuánto costó.

    Contesta "¿por qué el agente hizo eso?" tres días después, para una conversación
    concreta y sin grep. No se le manda al modelo: es para vos.
    """

    __tablename__ = "execution_steps"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # Sin index=True: el índice compuesto de __table_args__ empieza por
    # conversation_id y ya cubre este filtro.
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )

    # De qué ejecución es este paso. Es lo que hace contestable "¿cómo va ESTO
    # que pedí?" mientras corre — la conversación no alcanza, porque tiene
    # muchas corridas.
    #
    # Nullable porque no toda corrida tiene tarea: el endpoint sincrónico de
    # `/messages` y el de aprobaciones corren el agente sin crear una fila. Cuando
    # esas dos puertas pasen por `tasks`, la columna puede apretarse a NOT NULL.
    task_id: Mapped[str | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True
    )

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

    conversation: Mapped[Conversation] = relationship(back_populates="steps", lazy="raise")

    __table_args__ = (
        # "la traza de esta conversación, más nueva primero". Se declara ASC aunque la
        # query ordene DESC: Postgres recorre un btree hacia atrás sin problema.
        Index("ix_steps_conversation_created", "conversation_id", "created_at"),
        # "los pasos de esta tarea, en orden": la consulta del polling, que corre
        # cada pocos segundos mientras la tarea vive.
        Index("ix_steps_task_id", "task_id", "id"),
    )
