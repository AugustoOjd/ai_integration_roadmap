import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.routes.embeddings import router as embeddings_router
from app.services.embeddings import get_service

# uvicorn only configures its own loggers, leaving the root logger without a
# handler — without this, the log lines from routes/services would be swallowed.
logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warm ONLY the default model here rather than on the first request. Startup
    # is the right place to pay a multi-second cost: the alternative is one
    # unlucky user waiting for a download while everyone else queues behind them.
    #
    # The alternate model stays unloaded until something actually asks for it —
    # each loaded model costs ~1GB of RAM, so paying for one nobody uses would be
    # wasteful. That laziness is what makes declaring several models cheap.
    #
    # Note the tradeoff with --reload: every code change restarts the worker and
    # re-runs this. The model stays cached on disk, so it's a re-load into memory
    # (~1s), not a re-download.
    get_service("default").load()
    yield


app = FastAPI(title="Mini 3: Embeddings", lifespan=lifespan)

app.include_router(embeddings_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
