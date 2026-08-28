from fastapi import FastAPI

from app.routes import tasks

app = FastAPI(title="Mini 6 - Celery Basics")

app.include_router(tasks.router)


@app.get("/health")
def health() -> dict[str, str]:
    # Solo dice que la API está viva. No prueba que haya un worker escuchando:
    # se puede encolar sin workers y las tareas quedan esperando en Redis.
    return {"status": "ok"}
