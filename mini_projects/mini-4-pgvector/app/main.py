import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import EMBEDDING_DIM
from app.database import init_db

# Import con efecto secundario: registra Note en Base.metadata para que
# create_all lo vea. Sin esto init_db() no crea ninguna tabla.
from app.models.note import Note  # noqa: F401
from app.routes.notes import router as notes_router
from app.services.embeddings import embedding_service

# uvicorn solo configura sus loggers; sin esto el root logger no tiene handler.
logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")

# basicConfig pone el ROOT logger en INFO, así que también hablan las librerías.
# httpx narra cada HEAD al hub; huggingface_hub avisa de HF_TOKEN en cada carga.
for _noisy in ("httpx", "huggingface_hub", "sentence_transformers", "transformers"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)
logging.getLogger("huggingface_hub").setLevel(logging.ERROR)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Carga fuera del event loop. Además evita pagar los ~2s en el primer request.
    await asyncio.to_thread(embedding_service.load)

    # La columna es vector(384) fija: con otro modelo, cada INSERT moriría con
    # "expected 384 dimensions". Mejor fallar al arrancar que en producción.
    if embedding_service.dimension != EMBEDDING_DIM:
        raise RuntimeError(
            f"{embedding_service.model_name!r} devuelve {embedding_service.dimension} "
            f"dimensiones, pero la columna es vector({EMBEDDING_DIM}). "
            "Ajusta EMBEDDING_DIM y recrea la tabla."
        )

    await init_db()
    yield


app = FastAPI(title="Mini 4: pgvector Semantic Search", lifespan=lifespan)

# Monta las rutas de notes.py, ya prefijadas con /notes
app.include_router(notes_router)


@app.get("/health")
async def health():
    # Lo consulta el HEALTHCHECK del Dockerfile
    return {"status": "ok"}
