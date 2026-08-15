import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import init_db
from app.routes.notes import router as notes_router
from app.services.cache import redis_client

# uvicorn only configures its own loggers, leaving the root logger without a
# handler — without this, the CACHE HIT/MISS lines in routes/notes.py would be
# swallowed instead of printed to the console.
logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Runs once on startup, before the app accepts any requests
    await init_db()
    yield
    # Release Redis's connection pool cleanly on shutdown
    await redis_client.aclose()


app = FastAPI(title="Mini 2: Redis Caching", lifespan=lifespan)

# Mounts every route from notes.py (already prefixed with /notes) onto this app
app.include_router(notes_router)


@app.get("/health")
async def health():
    # Polled by the Dockerfile's HEALTHCHECK and docker-compose's depends_on
    return {"status": "ok"}
