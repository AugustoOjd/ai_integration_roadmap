"""Conexión a Postgres: engine, fábrica de sesiones y la dependencia de FastAPI.

Separado de `models.py` a propósito. Los modelos son declaraciones puras y se
pueden importar sin que haya una base levantada; este módulo, en cambio, abre un
pool de conexiones al importarse. Esa asimetría es la que permite que los tests
de la Fase 9 armen objetos en memoria sin Docker corriendo.
"""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.models import Base

# ---------------------------------------------------------------------------
# El engine
# ---------------------------------------------------------------------------

# Uno solo para todo el proceso, creado al importar. El engine NO es una
# conexión: es un pool de conexiones más la lógica del dialecto. Crear uno por
# request sería abrir y cerrar conexiones TCP a Postgres todo el tiempo, que es
# de lo más caro que podés hacerle a una base.
#
# `str(...)` sobre el DATABASE_URL no es decorativo: `PostgresDsn` es un objeto
# `Url` de Pydantic, no un string, y SQLAlchemy espera un string o su propio
# `URL`. Es el tropiezo clásico al usar los tipos de URL de Pydantic v2 — falla
# con un error de tipo poco claro si te lo olvidás.
engine: AsyncEngine = create_async_engine(
    str(settings.DATABASE_URL),
    # Imprime cada sentencia SQL. Ruidoso, pero es la forma más rápida de ver
    # que un `load_history` está haciendo N+1 queries (Fase 1).
    echo=settings.DB_ECHO,
    # Manda un "SELECT 1" antes de entregar una conexión del pool. Sin esto, una
    # conexión que murió mientras estaba guardada —porque Postgres se reinició,
    # o porque un firewall corta conexiones ociosas— se entrega igual y el
    # request falla con un error de conexión aparentemente aleatorio. El costo
    # es un round-trip por checkout; vale cada vez.
    pool_pre_ping=True,
    # Recicla conexiones más viejas que esto. Los proxies y balanceadores suelen
    # cortar conexiones ociosas a los 30-60 minutos sin avisar; reciclarlas
    # antes evita descubrirlo del lado malo.
    pool_recycle=1800,
    # Tamaño del pool. La cuenta real es: cuántas conexiones simultáneas puede
    # tener ESTE proceso, por cuántos procesos corras, contra el `max_connections`
    # de Postgres (100 por default). Acá los handlers pasan la mayor parte del
    # tiempo esperando a Anthropic, no a la base, así que un pool chico alcanza.
    pool_size=5,
    max_overflow=10,
)

# ---------------------------------------------------------------------------
# La fábrica de sesiones
# ---------------------------------------------------------------------------

# Una `AsyncSession` es la unidad de trabajo: acumula objetos, los rastrea y los
# vuelca a la base en un `flush`. Es barata de crear y NO es thread-safe ni
# compartible entre requests — por eso lo que se comparte es la fábrica, y cada
# request fabrica la suya.
#
# `expire_on_commit=False` es obligatorio en async, no una preferencia. Por
# default, después de un `commit()` SQLAlchemy marca todos los objetos como
# vencidos, y el primer atributo que toques dispara un SELECT para refrescarlos.
# En un contexto async ese SELECT implícito explota con `MissingGreenlet`. Con
# `False`, los objetos conservan los valores que ya tenían y podés devolverlos
# en la respuesta después de commitear, que es exactamente lo que hace un
# endpoint.
SessionFactory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ---------------------------------------------------------------------------
# La dependencia
# ---------------------------------------------------------------------------


async def get_db() -> AsyncIterator[AsyncSession]:
    """Entrega una sesión de base por request, y la cierra pase lo que pase.

    Nótese lo que esta función NO hace: **no commitea**. Es deliberado, y es la
    decisión que sostiene la Fase 1.

    La alternativa tentadora —commitear acá cuando el handler termina bien— hace
    que la transacción sea "todo el request". Suena cómodo hasta que el turno de
    un agente son varios pasos que tienen que ser atómicos entre sí (persistir
    el historial completo) conviviendo con otros que NO deben perderse si el
    turno falla (los pasos de la traza, Fase 4). Con el commit acá arriba, no
    tenés forma de expresar esa diferencia.

    Así que el commit lo hace quien sabe qué constituye una unidad de trabajo:
    el repositorio. Esta dependencia sólo garantiza que la sesión se cierra y
    que una excepción no deja una transacción abierta ocupando una conexión del
    pool.
    """
    async with SessionFactory() as session:
        try:
            yield session
        except Exception:
            # Sin esto, una excepción a mitad de un handler deja la transacción
            # abierta hasta que el pool recicle la conexión. En Postgres eso
            # significa locks retenidos y filas que nadie más puede tocar.
            await session.rollback()
            raise
        # No hay `finally: close()`: el `async with` ya lo hace, y devolver la
        # conexión al pool es justamente lo que hace `close()` en SQLAlchemy
        # (no cierra el socket).


# `Annotated` + `Depends` en un alias: en vez de repetir
# `db: AsyncSession = Depends(get_db)` en cada endpoint, se escribe `db: Db`.
# Es la forma recomendada desde FastAPI 0.95 y tiene una ventaja concreta sobre
# el default clásico: como el `Depends` está en la ANOTACIÓN y no en el valor
# por default, la función se puede llamar a mano (en un test, en un script) sin
# que el parámetro tenga un objeto `Depends` de relleno.
Db = Annotated[AsyncSession, Depends(get_db)]


# ---------------------------------------------------------------------------
# Creación del esquema
# ---------------------------------------------------------------------------


async def create_schema() -> None:
    """Crea las tablas que falten, a partir de los modelos.

    Esto es andamiaje de estudio, no una estrategia de esquema. `create_all` sólo
    sabe CREAR: no ve que una columna cambió de tipo, no borra lo que sacaste del
    modelo y no tiene forma de expresar "migrá los datos viejos a la forma
    nueva". El día que en la Fase 5 le agregues columnas a `sessions`, este
    helper no las va a agregar a una tabla que ya existe — y el síntoma va a ser
    un error de columna inexistente, no un aviso.

    En un proyecto real esto es Alembic: cada cambio de modelo genera un script
    versionado que corre en el deploy. Acá alcanza con esto porque tirar la base
    y rehacerla es gratis:

        docker compose down -v && docker compose up -d --wait
    """
    async with engine.begin() as conn:
        # `run_sync` es el puente entre los dos mundos: la creación del esquema
        # es una API sincrónica de SQLAlchemy, y esto la corre en el greenlet
        # del engine async sin bloquear el event loop.
        await conn.run_sync(Base.metadata.create_all)
