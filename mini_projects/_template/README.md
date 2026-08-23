# Plantilla de mini proyecto

Esqueleto común de los minis del roadmap. Copia, renombra, escribe el dominio.

```bash
cp -r _template mini-N-nombre
cd mini-N-nombre
```

## Qué toca cambiar

| Archivo | Qué |
|---|---|
| `pyproject.toml` | `name`, y añadir las deps del mini |
| `.env` | crear desde `.env.example`; ajustar `POSTGRES_PORT` si vas a tener varios minis levantados |
| `app/main.py` | título, importar los modelos (`noqa: F401`), montar los routers |
| `app/config.py` | campos nuevos si el mini los necesita |
| `docker-compose.yml` | servicios extra (Redis, etc.) o cambiar la imagen de Postgres |

## Arranque

```bash
cp .env.example .env
uv sync
docker compose up -d postgres
uv run uvicorn app.main:app --reload
uv run pytest -v          # test_health.py debe pasar en verde
```

O todo en contenedores:

```bash
docker compose up --build
```

El servicio `app` monta `./app` como volumen y corre con `--reload`, así que
editas en el host y el contenedor recarga. Quita esas dos líneas para probar la
imagen tal como se desplegaría.

## Qué trae resuelto

- **`app/database.py`** — `Base`, engine async, `get_db`, `init_db`. Idéntico en
  todos los minis; normalmente no se toca.
- **`app/main.py`** — `lifespan` que llama a `init_db`, logging configurado y
  `/health` (que es lo que consulta el `HEALTHCHECK` del Dockerfile).
- **`tests/conftest.py`** — crea y tira `mini_db_test` sola, una sesión por test
  con rollback, y `client` con `dependency_overrides`.
- **Dockerfile** con las capas en el orden correcto: deps antes que código, para
  que editar no reinstale nada.

## Trampas que ya están cubiertas

- `init_db()` solo crea tablas de modelos **importados** → el `noqa: F401` en `main.py`
- `depends_on: condition: service_healthy` → si no, `init_db()` corre antes de que
  Postgres acepte conexiones
- `pythonpath = ["."]` en pytest → porque `package = false` deja `app/` fuera del venv
- Los scripts se ejecutan con `python -m scripts.x`, no `python scripts/x.py`

## Estructura

```
app/
├── config.py        # Settings desde env vars
├── database.py      # engine, sesión, get_db, init_db
├── main.py          # lifespan, routers, /health
├── models/          # tablas SQLAlchemy
├── schemas/         # request/response Pydantic
├── services/        # lógica de dominio, sin saber de HTTP
└── routes/          # endpoints: traducen HTTP <-> servicios
scripts/             # seed, benchmarks (correr con python -m)
tests/
```

La separación que importa: **`services/` no debe importar nada de FastAPI**. Es lo
que permite reutilizar la lógica desde un worker de Celery en mini-6.
