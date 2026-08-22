"""Fixtures compartidas.

Los tests corren contra una base APARTE (`mini_db_test`), no contra mini_db:
las 10.000 notas del seed harían imposible afirmar nada sobre el ranking.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models.note import Note  # noqa: F401  registra la tabla en Base.metadata

# Misma conexión, distinta base. rsplit por si la contraseña llevara barras.
BASE_URL, _ = settings.DATABASE_URL.rsplit("/", 1)
ADMIN_URL = f"{BASE_URL}/postgres"
TEST_URL = f"{BASE_URL}/mini_db_test"


@pytest.fixture(scope="session")
async def engine():
    """Crea mini_db_test desde cero, con la extensión y las tablas."""
    # CREATE DATABASE no puede ir dentro de una transacción: de ahí AUTOCOMMIT.
    admin = create_async_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.execute(text("DROP DATABASE IF EXISTS mini_db_test"))
        await conn.execute(text("CREATE DATABASE mini_db_test"))
    await admin.dispose()

    test_engine = create_async_engine(TEST_URL)
    async with test_engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)

    yield test_engine
    await test_engine.dispose()


@pytest.fixture
async def db(engine):
    """Sesión que se deshace al terminar cada test.

    La sesión se ata a una conexión con transacción ya abierta: sus commit()
    quedan como savepoints y el rollback final los borra todos. Así los tests no
    se ven entre sí sin recrear la tabla cada vez.
    """
    async with engine.connect() as conn:
        trans = await conn.begin()
        session = AsyncSession(bind=conn, expire_on_commit=False)
        yield session
        await session.close()
        await trans.rollback()


@pytest.fixture
async def client(db):
    """Cliente HTTP contra la app, con get_db apuntando a la sesión del test."""
    app.dependency_overrides[get_db] = lambda: db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
async def notas(client):
    """Cuatro notas de dos temas bien separados, para poder afirmar el ranking."""
    datos = [
        {"title": "Python", "content": "Python is a powerful programming language"},
        {"title": "JavaScript", "content": "JavaScript runs in browsers and on servers"},
        {"title": "Sourdough", "content": "How to bake sourdough bread at home"},
        {"title": "Marathon", "content": "Training plan for running a marathon"},
    ]
    return [(await client.post("/notes/", json=d)).json() for d in datos]
