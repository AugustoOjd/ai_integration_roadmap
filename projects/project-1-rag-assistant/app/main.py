import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from app.config import EMBEDDING_DIM, settings
from app.database import init_db
from app.dependencies import log_startup_mode, rate_limit, require_api_key
from app.routes.chat import router as chat_router
from app.routes.documents import router as documents_router
from app.routes.search import router as search_router
from app.services.cache import redis_client
from app.services.embeddings import embedding_service

# Import por efecto secundario: registra las tablas en Base.metadata para que
# create_all las vea. Sin él, init_db() no crea nada.
from app.models.document import Document, DocumentChunk  # noqa: F401

# uvicorn solo configura sus loggers; sin esto el root logger no tiene handler.
logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")

# basicConfig pone el ROOT logger en INFO, así que también hablan las librerías.
for _noisy in ("httpx", "httpx2", "httpcore", "urllib3", "sentence_transformers", "transformers"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)
# ERROR y no WARNING: el aviso de HF_TOKEN es nivel WARNING.
logging.getLogger("huggingface_hub").setLevel(logging.ERROR)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Corre una vez al arrancar, antes de aceptar requests
    log_startup_mode()

    # Carga fuera del event loop. Ademas evita pagar los ~2s en el primer request.
    await asyncio.to_thread(embedding_service.load)

    # La columna es vector(384) fija: con otro modelo, cada INSERT moriria con
    # "expected 384 dimensions". Mejor fallar al arrancar.
    if embedding_service.dimension != EMBEDDING_DIM:
        raise RuntimeError(
            f"{embedding_service.model_name!r} devuelve {embedding_service.dimension} "
            f"dimensiones, pero la columna es vector({EMBEDDING_DIM})."
        )

    await init_db()
    yield
    # Libera el pool de conexiones de Redis al apagar
    await redis_client.aclose()


app = FastAPI(
    title="PROJECT 1: RAG Research Assistant",
    lifespan=lifespan,
    # /docs y /redoc solo en desarrollo.
    docs_url="/docs" if settings.is_dev else None,
    redoc_url="/redoc" if settings.is_dev else None,
    openapi_url="/openapi.json" if settings.is_dev else None,
)

# Administracion: clave obligatoria.
app.include_router(documents_router, dependencies=[Depends(require_api_key)])

# Recuperacion pura, sin LLM.
app.include_router(search_router)

# Publico, y el unico que gasta tokens: va con limite por IP.
app.include_router(chat_router, dependencies=[Depends(rate_limit)])


@app.get("/health")
async def health():
    # Sin autenticar a propósito: lo consulta el HEALTHCHECK del Dockerfile y
    # los orquestadores, que no llevan credenciales.
    return {"status": "ok"}
