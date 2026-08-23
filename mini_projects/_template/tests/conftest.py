"""Fixtures compartidas.

Los tests corren contra una base APARTE (`mini_db_test`), que se crea y se tira
sola: nunca tocan los datos con los que estás probando a mano.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base, get_db
from app.main import app  # noqa: F401  arrastra los modelos vía main.py

# Misma conexión, distinta base. rsplit por si la contraseña llevara barras.
BASE_URL, _ = settings.DATABASE_URL.rsplit("/", 1)
ADMIN_URL = f"{BASE_URL}/postgres"
TEST_URL = f"{BASE_URL}/mini_db_test"


@pytest.fixture(scope="session")
async def engine():
    """Crea mini_db_test desde cero, con las tablas."""
    # CREATE DATABASE no puede ir dentro de una transacción: de ahí AUTOCOMMIT.
    admin = create_async_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.execute(text("DROP DATABASE IF EXISTS mini_db_test"))
        await conn.execute(text("CREATE DATABASE mini_db_test"))
    await admin.dispose()

    test_engine = create_async_engine(TEST_URL)
    async with test_engine.begin() as conn:
        # Si el mini usa una extensión (pgvector, etc.), habilítala aquí antes.
        await conn.run_sync(Base.metadata.create_all)

    yield test_engine
    await test_engine.dispose()


@pytest.fixture
async def db(engine):
    """Sesión que se deshace al terminar cada test.

    La sesión se ata a una conexión con transacción ya abierta: con
    create_savepoint, los commit() de las rutas quedan como savepoints y el
    rollback final los borra. Así los tests no se ven entre sí sin recrear
    las tablas cada vez.
    """
    async with engine.connect() as conn:
        trans = await conn.begin()
        factory = async_sessionmaker(
            bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        session: AsyncSession = factory()
        yield session
        await session.close()
        await trans.rollback()


@pytest.fixture
async def client(db):
    """Cliente HTTP contra la app, con get_db apuntando a la sesión del test.

    Sin el override, la ruta abriría su propia sesión: lo que inserta el test y
    lo que ve la ruta estarían en transacciones distintas.
    """
    app.dependency_overrides[get_db] = lambda: db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
