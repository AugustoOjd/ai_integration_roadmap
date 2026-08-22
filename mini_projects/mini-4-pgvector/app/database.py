from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    """Base de la que hereda cada modelo (Note)."""


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
    """Registra pgvector y luego crea las tablas que dependen de él.

    El orden importa: create_all emite `embedding vector(384)` y Postgres
    rechaza un tipo desconocido.
    """
    async with engine.begin() as conn:
        # Duplica init.sql a propósito: ese archivo solo corre en un volumen
        # nuevo y no existe en Postgres gestionado (RDS, Supabase, Neon).
        # text() es obligatorio: SQLAlchemy 2.0 no acepta strings crudos.
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

        # Suficiente para un mini proyecto; en real serían migraciones Alembic.
        await conn.run_sync(Base.metadata.create_all)
