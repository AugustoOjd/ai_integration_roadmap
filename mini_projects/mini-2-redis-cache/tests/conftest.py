from collections.abc import AsyncGenerator

import pytest_asyncio
import redis.asyncio as redis
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.main import app    
from app.services import cache

# Separate database from the dev one (mini_db), so tests can never touch data
# you created by hand while poking at the API.
#
# One-time setup (Postgres won't create this for you):
#   docker-compose exec postgres psql -U postgres -c "CREATE DATABASE mini_db_test;"
TEST_DATABASE_URL = "postgresql+asyncpg://postgres:password@localhost:5432/mini_db_test"

# Redis database index 1 instead of the app's 0 — a Redis server holds 16
# numbered databases, so this isolates test keys from your dev cache without
# running a second Redis. Needed because flush_redis() below wipes it entirely.
TEST_REDIS_URL = "redis://localhost:6379/1"

test_engine = create_async_engine(TEST_DATABASE_URL)
test_redis = redis.from_url(TEST_REDIS_URL, decode_responses=True)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_database() -> AsyncGenerator[None, None]:
    """Create every table once before the whole test session, drop them after."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await test_redis.aclose()


@pytest_asyncio.fixture(autouse=True)
async def use_test_redis() -> AsyncGenerator[None, None]:
    """Point the cache service at the test Redis database, and wipe it before
    every test.

    Unlike Postgres, Redis takes no part in the transaction rollback below —
    a key cached by one test would still be there for the next one and quietly
    turn a "cache miss" path into a "hit". Flushing is what keeps tests isolated.

    Patching the module attribute works because cache.py's functions look up
    `redis_client` in module globals at call time, not at import time.
    """
    original_client = cache.redis_client
    cache.redis_client = test_redis
    await test_redis.flushdb()
    yield
    cache.redis_client = original_client


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """One session per test, wrapped in a transaction that's always rolled back.

    join_transaction_mode="create_savepoint" is required because route handlers
    call db.commit(): without it that commit would end our outer transaction for
    real, leaving the connection unusable for the next request in the same test.
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
    """HTTP client that calls the FastAPI app in-process (ASGITransport), with
    get_db swapped for our rolled-back test session."""

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
