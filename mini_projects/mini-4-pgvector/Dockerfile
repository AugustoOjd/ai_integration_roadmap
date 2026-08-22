FROM python:3.12-slim
WORKDIR /app

# curl solo para el HEALTHCHECK de abajo.
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Deps antes del código: al revés, cada edición reinstalaría torch.
# --frozen falla si uv.lock está desactualizado; --no-dev deja fuera pytest.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# sentence-transformers baja el modelo en el PRIMER USO, no al instalar. Sin
# esta capa, cada contenedor nuevo paga 88MB (~20s) y falla si no hay salida.
ENV HF_HOME=/opt/huggingface
RUN uv run python -c \
    "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# Último: editar código invalida solo esta capa.
COPY app/ app/

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
