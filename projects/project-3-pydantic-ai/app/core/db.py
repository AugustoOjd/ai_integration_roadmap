"""Engine async y fábrica de sesiones.

Separado de models.py: importar un modelo no debe abrir un pool.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

# Uno por proceso: no es una conexión, es un pool más el dialecto. str() porque
# PostgresDsn es un objeto Url y SQLAlchemy espera string.
engine: AsyncEngine = create_async_engine(
    str(settings.DATABASE_URL),
    echo=settings.DB_ECHO,
    # SELECT 1 antes de entregar una conexión: descarta las que murieron ociosas.
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
)

# expire_on_commit=False: si no, tocar un atributo después del commit dispara un
# refresco — I/O implícito en un `obj.campo`.
SessionFactory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@asynccontextmanager
async def session_scope() -> AsyncGenerator[AsyncSession, None]:
    """Una sesión, cerrada pase lo que pase. No commitea: eso lo decide quien llama."""
    async with SessionFactory() as session:
        try:
            yield session
        except Exception:
            # Sin esto la transacción retiene locks hasta que el pool recicle.
            await session.rollback()
            raise
