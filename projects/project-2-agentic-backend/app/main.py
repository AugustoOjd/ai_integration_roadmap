import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db import engine
from app.errors import install_error_handlers
from app.routes import approvals, sessions

# Sin esto los logger.info del agente no se ven: el nivel por default de Python es
# WARNING. En producción esto se reemplaza por logging estructurado (JSON), para
# que las líneas sean consultables y no sólo legibles.
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Lo que pasa una vez al arrancar y una vez al apagar.

    Es async porque el protocolo de lifespan de FastAPI lo exige, no porque adentro
    haya I/O asincrónico. Es la única función async del proyecto.

    El esquema NO se crea acá: lo aplica Alembic antes de arrancar la app.

    El engine.dispose() del final importa con --reload: cada recarga levanta un
    proceso nuevo, y sin el dispose las conexiones del proceso viejo quedan
    colgadas del lado de Postgres hasta agotar max_connections.
    """
    yield

    engine.dispose()


app = FastAPI(title="Project 2 - Agentic Backend", lifespan=lifespan)

# Una sola vez, sobre la app: a partir de acá las rutas se escriben sin `try`.
install_error_handlers(app)

app.include_router(sessions.router)
app.include_router(approvals.router)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness de la API y nada más.

    Deliberadamente no llama al modelo ni toca la base. Es el endpoint que mira un
    load balancer para decidir si mandarle tráfico a este proceso: tiene que ser
    instantáneo, gratis y no depender de terceros.

    Un /health que llama a Anthropic es un error con tres caras: le pagás a cada
    chequeo, gastás cuota de rate limit en algo que no es trabajo útil, y una caída
    del proveedor te saca de rotación una API que responde perfecto todo lo que no
    sea el agente.

    Chequear la base es otro endpoint (/ready) con otra semántica: "puedo
    trabajar", no "estoy vivo".
    """
    return {"status": "ok"}
