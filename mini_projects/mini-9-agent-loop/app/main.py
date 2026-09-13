import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db import create_schema, engine

# Sin esto los `logger.info` del agente no se ven: el nivel por default de
# Python es WARNING. En producción esto se reemplaza por logging estructurado
# (JSON), para que las líneas sean consultables y no sólo legibles.
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Lo que pasa una vez al arrancar y una vez al apagar.

    Es el reemplazo moderno de los viejos `@app.on_event("startup")`, y la
    diferencia no es cosmética: acá el arranque y el apagado son las dos mitades
    de una misma función, así que lo que abrís arriba del `yield` se cierra
    abajo sin que puedan desincronizarse.

    El `engine.dispose()` del final importa más de lo que parece con `--reload`:
    cada recarga levanta un proceso nuevo, y sin el dispose las conexiones del
    proceso viejo quedan colgadas del lado de Postgres hasta que se agota
    `max_connections` y la base deja de aceptar a cualquiera.
    """
    # ANDAMIAJE DE ESTUDIO, no cómo se hace en producción. Crear el esquema al
    # arrancar la app tiene dos problemas reales:
    #   1. `create_all` sólo sabe CREAR. Cuando en la Fase 5 le agregues columnas
    #      a `sessions`, no las va a agregar a la tabla existente (ver la nota
    #      en `db.py`).
    #   2. Con varios workers, todos corren esto a la vez contra la misma base.
    # En un proyecto real el esquema lo aplica un paso de deploy (Alembic), y la
    # app arranca asumiendo que ya está.
    await create_schema()

    yield

    await engine.dispose()


app = FastAPI(title="Mini 9 - Agent Loop", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness de la API y nada más.

    Deliberadamente NO llama al modelo ni toca la base. Este es el endpoint que
    mira un load balancer para decidir si mandarle tráfico a este proceso: tiene
    que ser instantáneo, gratis y no depender de terceros.

    Un /health que llama a Anthropic es un error con tres caras: le pagás a cada
    chequeo (y un LB chequea cada pocos segundos), gastás cuota de rate limit en
    algo que no es trabajo útil, y una caída del proveedor te saca de rotación
    una API que puede responder perfecto todo lo que no sea el agente.

    Si querés chequear la base, eso es un endpoint aparte (`/ready`) con otra
    semántica: "puedo trabajar", no "estoy vivo".
    """
    return {"status": "ok"}
