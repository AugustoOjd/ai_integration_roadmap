FROM python:3.12-slim
WORKDIR /app

# curl solo para el HEALTHCHECK de abajo.
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# `uv run` por default RE-SINCRONIZA el entorno antes de ejecutar, y esa sync sí
# incluye el grupo dev. Dentro del contenedor eso es doblemente malo: el venv lo
# creó root durante el build y el proceso corre como `celery`, así que el intento
# de escritura muere con "Permission denied" y el contenedor no arranca nunca.
# UV_NO_SYNC=1 le dice "el entorno ya está listo, solo ejecutá".
ENV UV_NO_SYNC=1

# El cache de uv y el venv caen en filesystems distintos (típico en WSL2), así
# que el hardlink falla y uv avisa en cada build. Copiar es lo correcto acá.
ENV UV_LINK_MODE=copy

# Deps antes del código: al revés, cada edición de un .py reinstalaría todo.
# --frozen falla si uv.lock está desactualizado; --no-dev deja fuera pytest.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Último: editar código invalida solo esta capa.
COPY app/ app/

# Una sola imagen para API y worker: mismo código, distinto command en compose.
# El worker NO debe correr como root (Celery se niega salvo que lo fuerces).
RUN useradd --create-home celery
USER celery

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
