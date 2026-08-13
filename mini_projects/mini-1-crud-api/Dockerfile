# Base image: match the Python version pinned in .python-version / pyproject.toml (>=3.12)
FROM python:3.12-slim

# All following instructions run from /app inside the container
WORKDIR /app

# build-essential: needed to compile some Python packages (e.g. psycopg) from source
# curl: used later by the HEALTHCHECK to ping the running app
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy the uv binary itself from Astral's official image instead of installing it via pip/curl
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy only dependency metadata first (not the source code yet).
# Docker caches this layer, so `uv sync` only reruns when these files change,
# not every time we edit application code.
COPY pyproject.toml uv.lock* README.md ./

# --no-install-project: install dependencies only, skip installing our own package
# (our package isn't copied in yet, so this would fail otherwise)
# --frozen: use uv.lock exactly as-is, don't try to re-resolve versions
RUN uv sync --frozen --no-install-project

# Now copy the actual application source (src/mini_1_crud_api/)
COPY src/ src/

# Install our own package into the venv now that its code is present
RUN uv sync --frozen

# Put the project's virtualenv on PATH so plain `python`/`uvicorn` also resolve correctly
ENV PATH="/app/.venv/bin:$PATH"

# Docker/orchestrators use this to know when the container is actually ready to serve traffic
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Document the port the app listens on (doesn't publish it by itself)
EXPOSE 8000

# Run the FastAPI app with uvicorn through uv, so it uses the project's venv
CMD ["uv", "run", "uvicorn", "mini_1_crud_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
