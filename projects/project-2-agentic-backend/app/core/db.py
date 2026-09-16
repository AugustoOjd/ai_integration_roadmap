"""Engine, fábrica de conversaciones y la dependencia de base de FastAPI.

Separado de models.py: los modelos se importan sin que haya una base levantada,
este módulo abre un pool al importarse.
"""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

# ---------------------------------------------------------------------------
# El engine
# ---------------------------------------------------------------------------

# Uno por proceso. El engine no es una conexión: es un pool más el dialecto.
# str() sobre el DSN es necesario: PostgresDsn es un objeto Url de Pydantic y
# SQLAlchemy espera un string.
engine: Engine = create_engine(
    str(settings.DATABASE_URL),
    echo=settings.DB_ECHO,
    # SELECT 1 antes de entregar una conexión del pool: evita que una conexión
    # muerta mientras estaba guardada llegue a un request.
    pool_pre_ping=True,
    # Los proxies suelen cortar conexiones ociosas a los 30-60 min sin avisar.
    pool_recycle=1800,
    # Con handlers sincrónicos cada request en vuelo retiene un thread y una
    # conexión, así que pool_size + max_overflow es el techo de concurrencia
    # contra la base. La suma por todos los procesos tiene que entrar en el
    # max_connections de Postgres (100 por default).
    pool_size=5,
    max_overflow=10,
)

# ---------------------------------------------------------------------------
# La fábrica de conversaciones
# ---------------------------------------------------------------------------

# La Session es la unidad de trabajo y no es thread-safe: se comparte la
# fábrica, cada request y cada tarea fabrica la suya.
# expire_on_commit=False: sin esto, tocar un atributo después de commit dispara
# un SELECT de refresco, y si la conversación ya cerró falla con DetachedInstanceError.
SessionFactory = sessionmaker(
    bind=engine,
    class_=Session,
    expire_on_commit=False,
)


# ---------------------------------------------------------------------------
# La dependencia
# ---------------------------------------------------------------------------


def get_db() -> Iterator[Session]:
    """Entrega una conversación por request y la cierra pase lo que pase.

    Es `def` y no `async def`: I/O sincrónico dentro de un `async def` corre en
    el event loop y bloquea toda la app. Declarada `def`, FastAPI la corre en su
    threadpool. La misma regla vale para todo handler que toque la base.

    No commitea a propósito. Si el commit viviera acá, la transacción sería
    "todo el request" y no habría forma de expresar que el historial de un turno
    es atómico pero los pasos de la traza no deben perderse si el turno falla.
    El commit lo hace el repositorio, que sabe qué es una unidad de trabajo.
    """
    with SessionFactory() as session:
        try:
            yield session
        except Exception:
            # Sin esto la transacción queda abierta hasta que el pool recicle la
            # conexión, reteniendo locks.
            session.rollback()
            raise
        # El `with` cierra la conversación, que en SQLAlchemy devuelve la conexión al
        # pool (no cierra el socket).


# Alias para escribir `db: Db` en vez de `db: Session = Depends(get_db)`. Al
# estar el Depends en la anotación y no en el default, la función se puede
# llamar a mano desde un test o una tarea.
Db = Annotated[Session, Depends(get_db)]


# El esquema lo maneja Alembic, no un create_all: las tablas cambian en varias
# fases y hay que conservar los datos entre una y otra.
#     uv run alembic revision --autogenerate -m "..."
#     uv run alembic upgrade head
