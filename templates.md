# 📋 Templates Listos para Copiar-Pegar

Usa estos templates para crear proyectos rápidamente.

---

# 1️⃣ pyproject.toml

## Mínimo (Mini Proyectos)

```toml
[project]
name = "mini-X-nombre"
version = "0.1.0"
description = "Mini project X"
authors = [{ name = "Your Name", email = "email@example.com" }]
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.109.0",
    "uvicorn[standard]>=0.27.0",
    "sqlalchemy[asyncio]>=2.0.25",
    "psycopg[binary]>=3.1.14",
    "pydantic>=2.5.3",
    "pydantic-settings>=2.1.0",
    "python-dotenv>=1.0.0",
]

[dependency-groups]
dev = [
    "pytest>=7.4.4",
    "pytest-asyncio>=0.23.3",
    "httpx>=0.26.0",
    "black>=23.12.0",
    "ruff>=0.1.8",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.black]
line-length = 100
target-version = ['py311']

[tool.ruff]
line-length = 100
target-version = "py311"
```

> Proyecto de aplicación (no se publica como paquete), por eso no lleva `[build-system]`. `uv sync` crea el `.venv` e instala todo esto automáticamente.

## Completo (Proyectos Grandes)

```toml
[project]
name = "project-rag-assistant"
version = "1.0.0"
description = "RAG Research Assistant API"
authors = [{ name = "Your Name", email = "email@example.com" }]
readme = "README.md"
license = "MIT"
requires-python = ">=3.11"
dependencies = [
    # Web framework
    "fastapi>=0.109.0",
    "uvicorn[standard]>=0.27.0",

    # Database & ORM
    "sqlalchemy[asyncio]>=2.0.25",
    "psycopg[binary]>=3.1.14",
    "pgvector>=0.2.1",
    "alembic>=1.13.0",

    # Data validation
    "pydantic>=2.5.3",
    "pydantic-settings>=2.1.0",

    # Caching & Queue
    "redis>=5.0.1",
    "celery>=5.3.4",

    # LLM & AI
    "anthropic>=0.20.0",
    "langchain>=0.1.0",
    "langchain-community>=0.0.34",

    # File processing
    "pypdf>=4.0.1",
    "python-multipart>=0.0.6",

    # Utils
    "python-dotenv>=1.0.0",
    "python-json-logger>=2.0.7",
]

[project.urls]
repository = "https://github.com/username/project-rag"

[dependency-groups]
dev = [
    "pytest>=7.4.4",
    "pytest-asyncio>=0.23.3",
    "pytest-cov>=4.1.0",
    "httpx>=0.26.0",
    "black>=23.12.0",
    "ruff>=0.1.8",
    "mypy>=1.7.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
addopts = "--cov=app --cov-report=html"

[tool.black]
line-length = 100
target-version = ['py311']

[tool.ruff]
line-length = 100
target-version = "py311"
select = ["E", "F", "I"]

[tool.mypy]
python_version = "3.11"
strict = true
warn_return_any = true
warn_unused_configs = true
```

---

# 2️⃣ docker-compose.yml

## Solo PostgreSQL

```yaml
version: '3.8'

services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: password
      POSTGRES_DB: mini_db
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  postgres_data:
```

## PostgreSQL + Redis

```yaml
version: '3.8'

services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: password
      POSTGRES_DB: mini_db
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  postgres_data:
```

## PostgreSQL + Redis + App + Celery Worker

```yaml
version: '3.8'

services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: password
      POSTGRES_DB: project_db
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

  app:
    build: .
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    ports:
      - "8000:8000"
    volumes:
      - .:/app
    environment:
      - DATABASE_URL=postgresql+asyncpg://postgres:password@postgres:5432/project_db
      - REDIS_URL=redis://redis:6379
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - DEBUG=true
    command: uvicorn app.main:app --host 0.0.0.0 --reload

  celery_worker:
    build: .
    depends_on:
      redis:
        condition: service_healthy
      postgres:
        condition: service_healthy
    environment:
      - DATABASE_URL=postgresql+asyncpg://postgres:password@postgres:5432/project_db
      - CELERY_BROKER_URL=redis://redis:6379
      - CELERY_RESULT_BACKEND=redis://redis:6379
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
    command: celery -A app.celery_app worker --loglevel=info

volumes:
  postgres_data:
```

---

# 3️⃣ Dockerfile

## Production Ready

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy project files
COPY pyproject.toml uv.lock* ./

# Install Python dependencies (cached layer, before copying app code)
RUN uv sync --frozen --no-install-project

# Copy app
COPY . .
RUN uv sync --frozen

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run
EXPOSE 8000
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

# 4️⃣ .env.example

## Mini Projects

```
# Database
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/mini_db

# Redis (if needed)
REDIS_URL=redis://localhost:6379

# API Keys
ANTHROPIC_API_KEY=sk-ant-...

# Settings
DEBUG=True
LOG_LEVEL=INFO
```

## Complete Projects

```
# Database
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/project_db

# Redis
REDIS_URL=redis://localhost:6379

# Celery
CELERY_BROKER_URL=redis://localhost:6379
CELERY_RESULT_BACKEND=redis://localhost:6379

# API Keys
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...

# Settings
DEBUG=False
LOG_LEVEL=INFO
ENVIRONMENT=production

# AWS (if using)
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...

# Monitoring
SENTRY_DSN=https://...
```

---

# 5️⃣ .gitignore

```
# Python
__pycache__/
*.pyc
*.pyo
*.pyd
.Python
*.egg-info/
dist/
build/
pip-log.txt
pip-delete-this-directory.txt
.tox/
.coverage
.coverage.*
.cache
nosetests.xml
coverage.xml
*.cover
.hypothesis/
.pytest_cache/
*.egg

# Virtual environments
venv/
env/
ENV/
.venv
.env
.env.local

# IDE
.vscode/
.idea/
*.swp
*.swo
*~
.DS_Store

# Logs
*.log
logs/

# Database
*.db
*.sqlite
*.sqlite3

# Redis
dump.rdb

# Celery
celerybeat-schedule

# OS
.DS_Store
Thumbs.db
```

---

# 6️⃣ app/config.py

## Mínimo

```python
from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:password@localhost:5432/mini_db"
    
    # Redis
    REDIS_URL: str = "redis://localhost:6379"
    
    # API
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    
    # LLM
    ANTHROPIC_API_KEY: str = ""
    
    class Config:
        env_file = ".env"
        case_sensitive = False

@lru_cache()
def get_settings() -> Settings:
    return Settings()
```

## Completo

```python
from pydantic_settings import BaseSettings
from functools import lru_cache
from enum import Enum

class Environment(str, Enum):
    DEV = "dev"
    STAGING = "staging"
    PROD = "prod"

class Settings(BaseSettings):
    # Environment
    ENVIRONMENT: Environment = Environment.DEV
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    
    # Database
    DATABASE_URL: str
    DATABASE_ECHO: bool = False
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 10
    
    # Redis
    REDIS_URL: str
    REDIS_POOL_SIZE: int = 10
    CACHE_TTL: int = 3600
    
    # Celery
    CELERY_BROKER_URL: str = ""
    CELERY_RESULT_BACKEND: str = ""
    
    # API Keys
    ANTHROPIC_API_KEY: str
    OPENAI_API_KEY: str = ""
    
    # Settings
    API_TITLE: str = "API"
    API_VERSION: str = "1.0.0"
    API_DESCRIPTION: str = ""
    CORS_ORIGINS: list[str] = ["*"]
    
    # AWS
    AWS_REGION: str = "us-east-1"
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    
    # Monitoring
    SENTRY_DSN: str = ""
    
    class Config:
        env_file = ".env"
        case_sensitive = False
        validate_default = True

@lru_cache()
def get_settings() -> Settings:
    return Settings()
```

---

# 7️⃣ app/database.py

## Básico

```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
)

async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

async def get_db():
    """Dependency for FastAPI routes"""
    async with async_session() as session:
        yield session

async def init_db():
    """Create tables on startup"""
    from sqlalchemy import text
    from app.models import Base  # Import all models
    
    async with engine.begin() as conn:
        # Enable extensions if needed
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        # Create tables
        await conn.run_sync(Base.metadata.create_all)
```

---

# 8️⃣ app/main.py

## Mínimo

```python
from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.database import init_db
from app.routes import your_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    yield
    # Shutdown

app = FastAPI(title="API", lifespan=lifespan)
app.include_router(your_router)

@app.get("/health")
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

## Completo

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.config import get_settings
from app.database import init_db
from app.services.cache import get_cache_service
from app.routes import documents, search, rag
import logging

settings = get_settings()
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting up...")
    await init_db()
    cache = await get_cache_service()
    
    yield
    
    # Shutdown
    logger.info("Shutting down...")
    await cache.disconnect()

app = FastAPI(
    title=settings.API_TITLE,
    version=settings.API_VERSION,
    lifespan=lifespan
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
app.include_router(documents.router)
app.include_router(search.router)
app.include_router(rag.router)

@app.get("/health")
async def health():
    return {"status": "ok", "environment": settings.ENVIRONMENT}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG
    )
```

---

# 9️⃣ app/celery_app.py

```python
from celery import Celery
import os

broker_url = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379")
result_backend = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379")

app = Celery(
    "celery_app",
    broker=broker_url,
    backend=result_backend,
)

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    
    # Task configuration
    task_track_started=True,
    task_time_limit=30 * 60,  # 30 min hard limit
    task_soft_time_limit=25 * 60,  # 25 min soft limit
    
    # Retry
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    
    # Results
    result_expires=3600,
)

# Auto-discover tasks
app.autodiscover_tasks(["app.tasks"])

@app.task(bind=True)
def debug_task(self):
    print(f"Request: {self.request!r}")
```

---

# 🔟 conftest.py (Testing)

```python
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.main import app
from app.database import get_db

@pytest.fixture
async def db():
    """Create test database"""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )
    
    async with engine.begin() as conn:
        from app.models import Base
        await conn.run_sync(Base.metadata.create_all)
    
    AsyncSessionLocal = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    
    async def override_get_db():
        async with AsyncSessionLocal() as session:
            yield session
    
    app.dependency_overrides[get_db] = override_get_db
    
    yield AsyncSessionLocal
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

@pytest.fixture
async def client():
    """Create test client"""
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac

@pytest.mark.asyncio
async def test_health(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
```

---

# 📝 Uso Rápido

```bash
# 1. Crea carpeta
mkdir mini-1-crud-api && cd mini-1-crud-api

# 2. Copia templates
cp path/to/templates/pyproject.toml .
cp path/to/templates/docker-compose.yml .
cp path/to/templates/Dockerfile .
cp path/to/templates/.env.example .env

# 3. Copia estructura app/
mkdir -p app/{models,schemas,routes}
touch app/{__init__.py,main.py,config.py,database.py}
touch app/{models,schemas,routes}/__init__.py

# 4. Setup
docker-compose up -d
uv sync
uv run uvicorn app.main:app --reload
```

¡Listo! Templates copiar-pegar para empezar rápido 🚀