import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import init_db

# TODO: importar aquí cada modelo, con noqa. Es un import por efecto secundario:
# registra la tabla en Base.metadata para que create_all la vea. Sin él,
# init_db() no crea nada.
# from app.models.mi_modelo import MiModelo  # noqa: F401

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


# TODO: cambiar el título por el del mini.
app = FastAPI(title="Mini X", lifespan=lifespan)

# TODO: montar los routers
# app.include_router(mi_router)


@app.get("/health")
async def health():
    # Lo consulta el HEALTHCHECK del Dockerfile
    return {"status": "ok"}
