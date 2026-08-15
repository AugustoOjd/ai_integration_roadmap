FROM python:3.12-slim
WORKDIR /app

# curl only needed for the HEALTHCHECK below
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# No [build-system] in pyproject.toml (this is an "app", not an installable
# package) so a single `uv sync` installs dependencies only — no project to
# install, no two-step cache trick needed like in mini-1.
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen

COPY app/ app/

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
