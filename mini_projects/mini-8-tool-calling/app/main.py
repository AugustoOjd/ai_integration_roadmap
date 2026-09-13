import logging

from fastapi import FastAPI

from app.routes import agent

# Sin esto los `logger.info` del agente no se ven: el nivel por default de
# Python es WARNING. En producción esto se reemplaza por logging estructurado
# (JSON), para que las líneas sean consultables y no sólo legibles.
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

app = FastAPI(title="Mini 8 - LLM Tool Calling")

app.include_router(agent.router)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness de la API y nada más.

    Deliberadamente NO llama al modelo para comprobar que la API key sirve. Este
    es el endpoint que mira un load balancer para decidir si mandarle tráfico a
    este proceso, y tiene que ser instantáneo, gratis y no depender de terceros.

    Un /health que llama a Anthropic es un error con tres caras a la vez: le
    pagás a cada chequeo (y un LB chequea cada pocos segundos), gastás cuota de
    rate limit en algo que no es trabajo útil, y una caída del proveedor te saca
    de rotación una API que puede responder perfecto todo lo que no sea el
    endpoint del agente.
    """
    return {"status": "ok"}
