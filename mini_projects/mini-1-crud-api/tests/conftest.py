from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from mini_1_crud_api.database import Base, get_db
from mini_1_crud_api.main import app

# Separate database from the one docker-compose creates for dev (mini_db), so
# running tests can never touch or wipe data you created manually while poking
# at the API. Same Postgres server, just a different database name.
#
# One-time setup (Postgres won't create this for you automatically):
#   docker-compose exec postgres psql -U postgres -c "CREATE DATABASE mini_db_test;"
TEST_DATABASE_URL = "postgresql+asyncpg://postgres:password@localhost:5432/mini_db_test"

test_engine = create_async_engine(TEST_DATABASE_URL)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_database() -> AsyncGenerator[None, None]:
    """Create every table once before the whole test session runs, drop them after.
    autouse=True means every test implicitly depends on this, no need to request it."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """One session per test, wrapped in a transaction that's always rolled back.
    This is what keeps tests isolated from each other without paying the cost
    of recreating tables for every single test.

    join_transaction_mode="create_savepoint" is required here: route handlers call
    db.commit() (see routes/notes.py). Without this, that commit() would end our
    outer `conn.begin()` transaction for real, leaving the connection in a state
    the next request can't safely reuse. With it, SQLAlchemy turns each inner
    commit() into a SAVEPOINT release instead, so the outer transaction — and the
    connection's protocol state — stays intact until we roll it back below.
    """
    async with test_engine.connect() as conn:
        await conn.begin()
        session_factory = async_sessionmaker(
            bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        session = session_factory()
        try:
            yield session
        finally:
            await session.close()
            await conn.rollback()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """HTTP client that calls the FastAPI app directly in-process (ASGITransport),
    no real server/port needed, with get_db swapped for our rolled-back test session."""

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
