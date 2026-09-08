from fastapi import FastAPI

from app.routes import dead_letter, tasks

app = FastAPI(title="Mini 7 - Task Retries & Monitoring")

app.include_router(tasks.router)
app.include_router(dead_letter.router)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness de la API y nada más.

    Deliberadamente NO consulta a Redis ni pregunta si hay workers vivos. Este
    es el endpoint que mira un load balancer para decidir si mandarle tráfico a
    este proceso: si lo hiciéramos depender de Redis, una caída del broker
    sacaría de rotación a una API que en realidad puede responder perfecto.

    "¿Hay quién ejecute las tareas?" es una pregunta distinta y vive en
    /monitoring (Fase 6). Mezclar las dos es un error clásico: se puede encolar
    sin un solo worker corriendo, y la cola espera.
    """
    return {"status": "ok"}
