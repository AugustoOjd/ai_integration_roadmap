"""Fixtures compartidas.

Regla que no se negocia: ningún test llama al modelo. Son lentos, cuestan plata y
no son determinísticos — un test que a veces pasa es peor que no tener test.

Se testea contra un Postgres de verdad, no contra SQLite en memoria. SQLite sería
más rápido y no necesitaría Docker, pero miente justo en lo que este proyecto usa:
no tiene JSONB (guardaría el historial como texto y el round-trip no probaría
nada), no tiene SELECT ... FOR UPDATE real, y difiere en CHECK constraints y
tipos. Un test que pasa contra una base que no es la tuya da confianza falsa.

El aislamiento entre tests no se consigue borrando tablas, sino envolviendo cada
uno en una transacción que nunca se commitea.
"""

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from anthropic.types import Message, MessageTokensCount, TextBlock, ToolUseBlock, Usage
from fastapi.testclient import TestClient

# `as sa_text` porque más abajo este módulo define su propio text() —el que fabrica
# un TextBlock del SDK— y el último en definirse gana. Sin el alias, el CREATE
# DATABASE falla con "Not an executable object: TextBlock(...)".
from sqlalchemy import Engine, create_engine, text as sa_text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.config import settings
from app.db import get_db
from app.deps import AgentDeps
from app.main import app
from app.models import Base, ChatSession

# La base de tests es OTRA base, no la de desarrollo: si fuera la misma, el seed te
# contamina la suite y un test que dice "el usuario tiene 2 pedidos" pasa a depender
# de cuántas veces lo corriste. Peor: un bug en un test puede borrarte los datos con
# los que estabas probando a mano.
#
# Se deriva del DATABASE_URL en vez de ser otro setting para que no puedan quedar
# apuntando a servidores distintos sin que nadie se dé cuenta.
_URL_DEV = make_url(str(settings.DATABASE_URL))
_URL_TEST = _URL_DEV.set(database=f"{_URL_DEV.database}_test")


def _crear_base_de_test() -> None:
    """Crea la base de tests si no existe.

    CREATE DATABASE no puede correr dentro de una transacción —limitación de
    Postgres, no de SQLAlchemy— y por eso hace falta isolation_level="AUTOCOMMIT".

    La conexión va contra la base `postgres`, que siempre existe: no podés
    conectarte a la base que estás por crear.
    """
    admin = create_engine(
        _URL_DEV.set(database="postgres"),
        isolation_level="AUTOCOMMIT",
        poolclass=NullPool,
    )
    with admin.connect() as conn:
        existe = conn.scalar(
            sa_text("select 1 from pg_database where datname = :nombre"),
            {"nombre": _URL_TEST.database},
        )
        if not existe:
            # El nombre va interpolado porque CREATE DATABASE no acepta parámetros
            # bindeados. Es seguro porque sale de tu propio DATABASE_URL.
            conn.execute(sa_text(f'CREATE DATABASE "{_URL_TEST.database}"'))
    admin.dispose()


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    """Un engine para toda la corrida de pytest.

    El esquema se crea con create_all y no con Alembic: la suite tiene que poder
    correr contra una base recién levantada sin un paso previo que alguien se
    olvide, y create_all es idempotente. Que el esquema de tests salga de los
    modelos y el de desarrollo de las migraciones es una divergencia real — si una
    migración queda mal escrita, los tests no lo ven. Se compensa aplicando las
    migraciones en CI antes de correr la suite.
    """
    _crear_base_de_test()

    motor = create_engine(_URL_TEST)
    Base.metadata.create_all(motor)

    yield motor

    motor.dispose()


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    """Una sesión cuyo trabajo se descarta al terminar el test.

    El patrón: abrir una conexión, arrancar una transacción EXTERNA a mano, y
    atarle la sesión. Al final se hace rollback de esa transacción y todo lo que el
    test escribió desaparece — sin TRUNCATE, sin recrear tablas, y sin que dos
    tests se pisen.

    La pieza que lo hace posible es join_transaction_mode="create_savepoint". El
    código bajo prueba COMMITEA de verdad (save_turn termina con db.commit(), que
    es justamente lo que queremos ejercitar). Sin esa opción, ese commit cerraría
    la transacción externa y el rollback final no tendría nada que deshacer. Con
    ella, cada commit de la aplicación libera un SAVEPOINT anidado: para el código
    es indistinguible de un commit, pero la transacción de afuera sigue abierta.
    """
    with engine.connect() as conn:
        transaccion = conn.begin()

        sesion = Session(
            bind=conn,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield sesion
        finally:
            sesion.close()
            transaccion.rollback()


@pytest.fixture
def client(db: Session) -> Iterator[TestClient]:
    """Un cliente HTTP contra la app, compartiendo la sesión de base del test.

    La pieza es dependency_overrides: se reemplaza get_db por una función que
    devuelve LA MISMA sesión que usa el test. Sin eso el endpoint abriría su propia
    sesión, escribiría en otra transacción, y el test no vería nada de lo que el
    endpoint hizo (ni el endpoint lo que preparó el test).

    El TestClient no se usa como context manager a propósito: así no corre el
    lifespan de la app, que haría un engine.dispose() del engine global después de
    cada test.
    """
    app.dependency_overrides[get_db] = lambda: db

    yield TestClient(app)

    # Limpiar SIEMPRE: `app` es un objeto de módulo compartido por toda la suite, y
    # un override que queda puesto se filtra al test siguiente y produce fallas que
    # dependen del orden en que corran los tests.
    app.dependency_overrides.clear()


@pytest.fixture
def chat(db: Session) -> ChatSession:
    """Una sesión de chat ya persistida, punto de partida de casi todo.

    Presupuesto chico y explícito, no el de config: un test que depende de un
    default global cambia de significado el día que alguien toca el .env.
    """
    sesion = ChatSession(user_id="u_42", budget_tokens=10_000)
    db.add(sesion)
    db.commit()
    return sesion


@pytest.fixture
def deps(db: Session, chat: ChatSession) -> AgentDeps:
    """El contexto autenticado, como lo arma la ruta."""
    return AgentDeps(user_id=chat.user_id, session_id=chat.id, db=db)


# ---------------------------------------------------------------------------
# El modelo falso
# ---------------------------------------------------------------------------
# Se usan los tipos REALES del SDK y no diccionarios sueltos: si una versión nueva
# cambia la forma de un bloque, estos tests se rompen al construirlos. Ese rojo es
# la alarma que querés — con dicts falsos el cambio pasaría hasta producción.


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
    cliente para después inspeccionar CON QUÉ se lo llamó — que acá es la mitad de
    lo interesante, porque lo que se verifica es qué historial se le mandó.

    Se parchea get_client y no run_agent: mockear run_agent no testearía nada, es el
    código bajo prueba. La frontera correcta para el mock es la más externa posible.
    """

    def _configurar(*responses: Message, estimado: int = 100) -> MagicMock:
        fake = MagicMock()
        # side_effect con una lista devuelve un elemento por llamada, en orden: es lo
        # que deja guionar una conversación entera.
        fake.messages.create = MagicMock(side_effect=list(responses))

        # La estimación del presupuesto. Valor fijo y bajo por default para que los
        # tests que no van sobre el presupuesto no tengan que pensar en él.
        fake.messages.count_tokens = MagicMock(
            return_value=MessageTokensCount(input_tokens=estimado)
        )

        monkeypatch.setattr("app.agent.get_client", lambda: fake)
        return fake

    return _configurar
