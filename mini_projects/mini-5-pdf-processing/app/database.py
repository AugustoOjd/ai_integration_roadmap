from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    """Base de la que hereda cada modelo."""


# El engine es dueño del pool de conexiones a Postgres.
engine = create_async_engine(settings.DATABASE_URL, echo=False)

# expire_on_commit=False: los atributos se siguen leyendo tras el commit sin un
# query extra de refresh.
async_session = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependencia de FastAPI: abre sesión, la pasa a la ruta, la cierra."""
    async with async_session() as session:
        yield session


async def init_db() -> None:
    """Crea las tablas de los modelos registrados en Base.

    Solo ve los modelos que hayan sido IMPORTADOS — de ahí el import con noqa
    en main.py. Suficiente para un mini; en real serían migraciones Alembic.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
