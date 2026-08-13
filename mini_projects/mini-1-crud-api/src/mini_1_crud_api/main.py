from contextlib import asynccontextmanager

from fastapi import FastAPI

from mini_1_crud_api.database import init_db
from mini_1_crud_api.routes.notes import router as notes_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Runs once on startup, before the app accepts any requests
    await init_db()
    yield
    # (nothing to clean up on shutdown for this mini project)


app = FastAPI(title="Mini 1: CRUD API", lifespan=lifespan)

# Mounts every route from notes.py (already prefixed with /notes) onto this app
app.include_router(notes_router)


@app.get("/health")
async def health():
    # Polled by the Dockerfile's HEALTHCHECK and docker-compose's depends_on
    return {"status": "ok"}
