from fastapi import FastAPI

app = FastAPI(title="Mini 8 - LLM Tool Calling")


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
