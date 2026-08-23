import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import init_db

# Import por efecto secundario: registra las tablas en Base.metadata para que
# create_all las vea. Sin él, init_db() no crea nada.
from app.models.document import Document, DocumentChunk  # noqa: F401
from app.routes.documents import router as documents_router

# uvicorn solo configura sus loggers; sin esto el root logger no tiene handler.
logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")

# basicConfig pone el ROOT logger en INFO, así que también hablan las librerías.
for _noisy in ("httpx", "urllib3"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Corre una vez al arrancar, antes de aceptar requests
    await init_db()
    yield
    # Aquí va el cierre limpio de clientes externos (Redis, colas, etc.)


app = FastAPI(title="Mini 5: PDF Upload & Chunking", lifespan=lifespan)

app.include_router(documents_router)


@app.get("/health")
async def health():
    # Lo consulta el HEALTHCHECK del Dockerfile
    return {"status": "ok"}
