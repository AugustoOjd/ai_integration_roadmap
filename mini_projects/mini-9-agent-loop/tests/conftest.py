"""Fixtures compartidas.

La regla del mini 8 sigue en pie: **ningún test llama al modelo**. Lo que este
mini agrega es una segunda dependencia lenta —la base— y con ella una pregunta
nueva: ¿contra qué Postgres se testea?

La respuesta es "contra uno de verdad", y no es pereza. SQLite en memoria sería
más rápido y no necesitaría Docker, pero miente justo en lo que este mini usa:
no tiene JSONB (guardaría el historial como texto y el round-trip no probaría
nada), no tiene `SELECT ... FOR UPDATE` real, y sus CHECK constraints y su
manejo de tipos difieren. Un test que pasa contra una base que no es la tuya te
da confianza falsa, que es peor que no tener test.

El aislamiento entre tests no se consigue borrando tablas, sino envolviendo cada
uno en una transacción que nunca se commitea.
"""

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
from anthropic.types import Message, MessageTokensCount, TextBlock, ToolUseBlock, Usage
from httpx import ASGITransport, AsyncClient
# `as sa_text` porque más abajo este módulo define su propio `text()` —el que
# fabrica un TextBlock del SDK— y el último en definirse gana. Sin el alias, la
# fábrica de bloques sombrea al `text()` de SQLAlchemy y el CREATE DATABASE
# falla con un "Not an executable object: TextBlock(...)" que no dice nada sobre
# la causa real.
from sqlalchemy import text as sa_text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.db import get_db
from app.deps import AgentDeps
from app.main import app
from app.models import Base, ChatSession

# La base de tests es OTRA base, no la de desarrollo: si es la misma,
# `seed_orders` te contamina la suite y un test que dice "el usuario tiene 2
# pedidos" pasa a depender de cuántas veces corriste el seed. Peor: un bug en un
# test puede borrarte los datos con los que estabas probando a mano.
#
# Se deriva del DATABASE_URL en vez de ser otro setting para que no puedan
# quedar apuntando a servidores distintos sin que nadie se dé cuenta.
_URL_DEV = make_url(str(settings.DATABASE_URL))
_URL_TEST = _URL_DEV.set(database=f"{_URL_DEV.database}_test")

# `CREATE DATABASE` una vez por corrida de pytest, no una por test.
_base_creada = False


async def _asegurar_base_de_test() -> None:
    """Crea la base de tests si no existe.

    `CREATE DATABASE` no puede correr dentro de una transacción —es una
    limitación de Postgres, no de SQLAlchemy— y por eso hace falta
    `isolation_level="AUTOCOMMIT"`. Sin eso, el driver abre una transacción
    implícita y el comando falla.

    La conexión va contra la base `postgres`, que siempre existe: no podés
    conectarte a la base que estás por crear.
    """
    global _base_creada
    if _base_creada:
        return

    admin = create_async_engine(
        _URL_DEV.set(database="postgres"),
        isolation_level="AUTOCOMMIT",
        poolclass=NullPool,
    )
    async with admin.connect() as conn:
        existe = await conn.scalar(
            sa_text("select 1 from pg_database where datname = :nombre"),
            {"nombre": _URL_TEST.database},
        )
        if not existe:
            # El nombre va interpolado porque `CREATE DATABASE` no acepta
            # parámetros bindeados. Es seguro acá porque sale de tu propio
            # DATABASE_URL, no de una entrada externa.
            await conn.execute(sa_text(f'CREATE DATABASE "{_URL_TEST.database}"'))
    await admin.dispose()

    _base_creada = True


@pytest.fixture
async def engine() -> AsyncGenerator[AsyncEngine, None]:
    """Un engine por test, sin pool.

    `NullPool` —abrir y cerrar la conexión cada vez, sin guardarla— es la pieza
    que hace que esto funcione con pytest-asyncio. Cada test corre en su propio
    event loop, y una conexión de asyncpg está atada al loop donde nació: una
    conexión guardada en el pool por el test anterior explota, en el siguiente,
    con errores de "attached to a different loop" que no tienen nada que ver con
    lo que estás testeando.

    El precio es abrir una conexión TCP por test. A esta escala no se nota.
    """
    await _asegurar_base_de_test()

    motor = create_async_engine(_URL_TEST, poolclass=NullPool)

    # `create_all` es idempotente: sólo crea lo que falta. Correrlo por test es
    # un par de queries de reflexión de más, a cambio de que la suite funcione
    # en una base recién levantada sin un paso previo que alguien se olvide.
    async with motor.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield motor

    await motor.dispose()


@pytest.fixture
async def db(engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Una sesión de base cuyo trabajo se descarta al terminar el test.

    El patrón es: abrir una conexión, arrancar una transacción EXTERNA a mano, y
    atarle la sesión. Al final se hace rollback de esa transacción externa y
    todo lo que el test escribió desaparece — sin `TRUNCATE`, sin recrear
    tablas, y sin que dos tests se pisen.

    La pieza que lo hace posible es `join_transaction_mode="create_savepoint"`.
    El código bajo prueba COMMITEA de verdad (`save_turn` termina con
    `db.commit()`, y eso es exactamente lo que queremos ejercitar). Sin esta
    opción, ese commit cerraría la transacción externa y el rollback final no
    tendría nada que deshacer. Con ella, cada `commit()` de la aplicación se
    traduce en liberar un SAVEPOINT anidado: para el código es indistinguible de
    un commit, pero la transacción de afuera sigue abierta y bajo nuestro
    control.
    """
    async with engine.connect() as conn:
        transaccion = await conn.begin()

        sesion = AsyncSession(
            bind=conn,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield sesion
        finally:
            await sesion.close()
            await transaccion.rollback()


@pytest.fixture
async def client(db: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Un cliente HTTP contra la app, compartiendo la sesión de base del test.

    La pieza es `dependency_overrides`: se reemplaza `get_db` por una función
    que devuelve LA MISMA sesión que usa el test. Sin eso, el endpoint abriría
    su propia sesión, escribiría en otra transacción, y el test no vería nada de
    lo que el endpoint hizo (ni el endpoint lo que preparó el test).

    Es `ASGITransport` y no un servidor de verdad: los requests entran a la app
    en el mismo proceso, sin puerto, sin red y sin event loop aparte. Más rápido
    y, sobre todo, sin la carrera de "¿ya levantó el servidor?".

    Ojo con `lifespan`: este transporte NO lo corre, así que `create_schema()`
    no se ejecuta acá. Está bien, porque de eso ya se encargó el fixture
    `engine`.
    """
    app.dependency_overrides[get_db] = lambda: db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as http:
        yield http

    # Limpiar SIEMPRE. `app` es un objeto de módulo, compartido por toda la
    # suite: un override que queda puesto se filtra al test siguiente y produce
    # fallas que dependen del orden en que corran los tests, que son las peores
    # de diagnosticar.
    app.dependency_overrides.clear()


@pytest.fixture
async def chat(db: AsyncSession) -> ChatSession:
    """Una sesión de chat ya persistida, que es el punto de partida de casi todo.

    Presupuesto chico y explícito, no el de config: un test que depende de un
    default global cambia de significado el día que alguien toca el `.env`.
    """
    sesion = ChatSession(user_id="u_42", budget_tokens=10_000)
    db.add(sesion)
    await db.commit()
    return sesion


@pytest.fixture
def deps(db: AsyncSession, chat: ChatSession) -> AgentDeps:
    """El contexto autenticado, como lo arma la ruta."""
    return AgentDeps(user_id=chat.user_id, session_id=chat.id, db=db)


# ---------------------------------------------------------------------------
# El modelo falso
# ---------------------------------------------------------------------------
# La regla del mini 8 sigue en pie: **ningún test llama al modelo**. Son lentos,
# cuestan plata y no son determinísticos — un test que a veces pasa es peor que
# no tener test, porque te entrena a ignorar el rojo.
#
# Usamos los tipos REALES del SDK y no diccionarios sueltos. Cuesta un poco más
# y vale la pena: si una versión nueva del SDK cambia la forma de un bloque,
# estos tests se rompen al construirlos. Ese rojo es exactamente la alarma que
# querés — con dicts falsos, el cambio pasaría desapercibido hasta producción.


def text(content: str) -> TextBlock:
    return TextBlock(type="text", text=content)


def tool_use(tool_id: str, name: str, **tool_input: object) -> ToolUseBlock:
    return ToolUseBlock(type="tool_use", id=tool_id, name=name, input=tool_input)


def response(
    *blocks: TextBlock | ToolUseBlock,
    stop_reason: str = "end_turn",
    tokens: tuple[int, int] = (10, 5),
) -> Message:
    """Una respuesta del modelo, fabricada a mano."""
    return Message(
        id="msg_test",
        type="message",
        role="assistant",
        model="claude-haiku-4-5",
        content=list(blocks),
        stop_reason=stop_reason,
        usage=Usage(input_tokens=tokens[0], output_tokens=tokens[1]),
    )


@pytest.fixture
def fake_model(monkeypatch: pytest.MonkeyPatch):
    """Reemplaza el cliente de Anthropic por uno que devuelve lo que vos digas.

    Devuelve una función: le pasás las respuestas en orden y te da el mock del
    cliente, para después inspeccionar CON QUÉ se lo llamó — que en este mini es
    la mitad de lo interesante, porque lo que queremos verificar es qué
    historial se le mandó.

    Se parchea `get_async_client` y no `run_agent`: si mockearas `run_agent` no
    estarías testeando nada, es justamente el código bajo prueba. La frontera
    correcta para el mock es la más externa posible — acá, la llamada HTTP.
    """

    def _configurar(*responses: Message, estimado: int = 100) -> MagicMock:
        fake = MagicMock()
        # `side_effect` con una lista devuelve un elemento por llamada, en
        # orden. Es lo que deja guionar una conversación entera: primero pide
        # una tool, después contesta.
        fake.messages.create = AsyncMock(side_effect=list(responses))

        # La estimación de la Fase 7. Se devuelve un valor fijo y bajo por
        # default para que los tests que no van sobre el presupuesto no tengan
        # que pensar en él; los que SÍ van, lo suben.
        fake.messages.count_tokens = AsyncMock(
            return_value=MessageTokensCount(input_tokens=estimado)
        )

        monkeypatch.setattr("app.agent.get_async_client", lambda: fake)
        return fake

    return _configurar
