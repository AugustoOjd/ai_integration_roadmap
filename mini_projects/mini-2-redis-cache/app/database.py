from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    """Base class every SQLAlchemy model (e.g. Note) inherits from."""


# The engine owns the pool of actual connections to Postgres.
engine = create_async_engine(settings.DATABASE_URL, echo=False)

# Factory for creating new AsyncSession objects bound to that engine.
# expire_on_commit=False keeps model attributes usable after commit (e.g. in the
# response) without triggering an extra query to refresh them.
async_session = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: opens a session, hands it to the route, closes it after."""
    async with async_session() as session:
        yield session


async def init_db() -> None:
    """Create all tables from models registered on Base. Fine for a mini project;
    a real app would use Alembic migrations instead of create_all."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
