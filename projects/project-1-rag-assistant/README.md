# 🎯 PROJECT 1: RAG Research Assistant

**Complete integration of Mini Projects 1-5**

Integrate everything you've learned into a production-ready RAG (Retrieval Augmented Generation) system.

## 📌 When to Start This Project

**Prerequisites:** Complete Mini 1-5 first

```
Mini 1 → Mini 2 → Mini 3 → Mini 4 → Mini 5 ✅
                                        ↓
                                  PROJECT 1 ← You are here
```

**Timeline:** Week 4-5 (after ~20 hours of mini projects)

## 🎯 What You'll Build

A complete RAG system that:
1. Accepts document uploads (PDF/text)
2. Chunks and indexes with embeddings
3. Searches semantically
4. Returns LLM-generated answers with citations

**Real-world use case:** Research assistant, documentation search, Q&A system

### Corpus: data, not product

Nothing in this app is domain-specific. The corpus arrives through
`POST /documents/upload` like any other file, so swapping the subject matter is an
upload, never a code change.

**Test corpus:** the Riftbound TCG rulebook and FAQ — chosen deliberately, because
a good corpus for *developing* a RAG has three properties:

| Property | Why it matters |
|---|---|
| The base LLM doesn't know it | Proves the answer came from **retrieval**, not from model memory. With a corpus the model already knows, a correct answer tells you nothing. |
| Questions have verifiable answers | Lets you build an eval set and actually **measure** whether `CHUNK_SIZE` was a good choice — the metric Mini 5 could not provide. |
| Questions repeat across users | The Redis cache gets a real hit ratio instead of being decorative. |

Any rulebook, manual, or reference work with those properties does the job. Swap
it for a different game, a legal code, or an API reference and the system behaves
the same.

**What that forbids in the code:**

- No prompt that names the domain — the system prompt says *"answer only from the
  provided context, cite your sources, refuse when the context is insufficient"*
  and nothing more
- No parsing tied to one document's structure (rule numbers, card names)
- Chunk metadata stays generic: `source`, `page`, `section` — meaningful for a
  rulebook and for a novel alike
- The eval set is a fixture that ships with the corpus, not code

## 🏗️ Architecture

```
┌─────────────────────────────────────────────┐
│         FastAPI Application                  │
├─────────────────────────────────────────────┤
│                                             │
│  POST /documents/upload                     │
│    ├─ Accept PDF/text                       │
│    ├─ Extract text (Mini 5)                 │
│    ├─ Chunk text (Mini 5)                   │
│    ├─ Generate embeddings (Mini 3)          │
│    └─ Store in pgvector (Mini 4)            │
│                                             │
│  POST /search/query                         │
│    ├─ Embed query (Mini 3)                  │
│    ├─ Search pgvector (Mini 4)              │
│    ├─ Retrieve top-K chunks                 │
│    ├─ Check Redis cache (Mini 2)            │
│    ├─ Send to LLM with context              │
│    └─ Stream response                       │
│                                             │
│  POST /chat  ·  POST /chat/stream           │
│    └─ Full RAG pipeline (all above)         │
│                                             │
└─────────────────────────────────────────────┘
        ↓              ↓              ↓
   PostgreSQL       Redis          Anthropic
   (pgvector)       (cache)        (answers only)
                                        ↑
              embeddings run LOCALLY via sentence-transformers (Mini 3):
              Anthropic has no embeddings API, and nothing leaves the machine
              during ingestion.
```

## 📚 Tech Stack

### Core
- **FastAPI** 0.141+ - Web framework
- **Python** 3.12+ - Runtime
- **uv** - Dependency management
- **Uvicorn** - ASGI server

### Database & Storage
- **PostgreSQL** 16 - Primary database
- **pgvector** - Vector storage & search
- **Redis** 7+ - Caching layer
- **SQLAlchemy** 2.0+ - Async ORM

### AI/LLM
- **Anthropic Claude** (`claude-opus-5`) - LLM for answers
- **sentence-transformers** (`all-MiniLM-L6-v2`, 384-D) - Embeddings, run locally
- **LangChain** - Not used. Mini 3-5 built these pieces by hand on purpose;
  see `mini-4-pgvector/APRENDIZAJES.md`

### Infrastructure
- **Docker** - Containerization
- **Docker Compose** - Local orchestration
- **Terraform** - Infrastructure as Code (AWS)
- **GitHub Actions** - CI/CD

### Deployment
- **Railway** - Easy deployment (free tier)
- **AWS** - Production deployment
  - RDS (PostgreSQL)
  - ECS (containerized app)
  - S3 (file storage)

## 🚀 Quick Start

### Prerequisites

```bash
Python 3.12+
uv
Docker + Docker Compose
ANTHROPIC_API_KEY=sk-ant-...
```

### Local Setup

```bash
# 1. Navigate to project
cd projects/project-1-rag-assistant

# 2. Install dependencies
uv sync

# 3. Setup environment
cp .env.example .env
# Edit .env with your ANTHROPIC_API_KEY

# 4. Start services
docker compose up -d postgres redis

# Verify database is ready
docker compose ps          # both must say "healthy", not just "running"

# 5. Start app — init_db() creates the tables on startup
uv run uvicorn app.main:app --reload

# 6. Test
curl http://localhost:8000/health
open http://localhost:8000/docs   # Interactive API docs
```

> **Note on migrations.** Mini 1-5 used `Base.metadata.create_all()` from the
> `lifespan`, and this project can start the same way. Alembic is the real answer
> once the schema starts changing, but it is not a prerequisite for getting the
> pipeline running — add it when a column change first forces you to drop the
> database.

> **Starting from the template.** `mini_projects/_template/` has the skeleton
> already resolved (config, database, lifespan, `/health`, Dockerfile). Two things
> to change here: the Postgres image must be `pgvector/pgvector:pg16`, and you need
> a `redis` service.

### Ingest and measure

```bash
# 1. Upload the corpus (admin — needs X-API-Key when API_KEY is set)
curl -X POST http://localhost:8000/documents/upload -F "file=@rulebook.pdf"

# 2. Build the vector index — AFTER ingesting, never before
uv run python -m scripts.create_index

# 3. Score the eval set
uv run python -m scripts.evaluate
```

> ⚠️ **Never build an IVFFlat index on an empty table.** It learns its cluster
> centroids from the rows present at build time, and a query only scans
> `ivfflat.probes` clusters (**1** by default). Built empty, the centroids are
> meaningless and the search returns **zero rows** — no error, no warning. That is
> why the index is not declared on the model, where `create_all()` would build it
> before any data exists. Re-run `create_index` after every ingestion.

`scripts/evaluate.py` reports **two separate numbers**, and that separation is the
whole point:

```
REC  RESP   question
 ok    ok   What is a champion legend?
 NO    NO   How many runes do I get each turn?
 ok    NO   What decides the outcome of a fight?
```

| Pattern | Where the problem is |
|---|---|
| `NO / NO` | Retrieval — tune `CHUNK_SIZE`, `TOP_K`, or the embedding model |
| `ok / NO` | Generation — tune the prompt or the model |
| `ok / ok` | Working |

It prints the configuration it ran with, so two runs can be compared. This is what
replaces eyeballing a single query: change `CHUNK_SIZE`, re-ingest, re-score, and
read the difference.

## 📝 API Endpoints

### Document Management

```bash
# Upload document
POST /documents/upload
Content-Type: multipart/form-data
file: document.pdf

Response:
{
  "id": "doc-123",
  "filename": "document.pdf",
  "chunks_count": 42
}

# List documents
GET /documents/

# Get document chunks
GET /documents/{doc_id}/chunks
```

### Retrieval only — no LLM

```bash
POST /search/query
{ "query": "how do I win the game?", "top_k": 5 }

Response:
{
  "query": "how do I win the game?",
  "results": [
    { "source": "rulebook.pdf", "page": 12, "section": null,
      "chunk": "...", "similarity": 0.43 }
  ]
}
```

**This endpoint is the debugging tool that matters.** When an answer is wrong,
it separates the two possible causes: bad retrieval, or good retrieval and bad
generation. Without it you end up tuning the prompt to fix a chunking problem.

### RAG (full pipeline)

```bash
POST /chat
{
  "query": "and how many domains does it have?",
  "history": [
    { "role": "user", "content": "what is a legend?" },
    { "role": "assistant", "content": "A legend is..." }
  ]
}

Response:
{
  "answer": "Two domains [1].",
  "sources": [ { "n": 1, "source": "rulebook.pdf", "page": 3, "similarity": 0.43 } ]
}
```

- `history` is optional. It is **truncated server-side** to the last
  `MAX_HISTORY_TURNS` and `MAX_HISTORY_CHARS`, and `role` accepts only
  `user`/`assistant` — the system prompt is always the server's.
- Retrieval prepends the previous user turn to the search query, so follow-ups
  like *"and how many does it have?"* still find the right chunks. The LLM
  receives the original question.
- Answers without history are cached in Redis. A repeat question returns with
  `X-Cache: HIT` and costs no tokens. Uploading or deleting a document bumps a
  version counter that invalidates every cached answer at once.

### Streaming

```bash
POST /chat/stream     # same body as /chat
```

Server-Sent Events. Sources arrive first so the UI can render citations while
the text is still being written:

```
data: {"type":"sources","sources":[...]}
data: {"type":"delta","text":"Two "}
data: {"type":"delta","text":"domains"}
data: {"type":"done"}
```

Not cached: emitting chunk by chunk and reassembling to store would defeat the
point. Send repeat questions to `/chat`.

### Authentication

Admin endpoints (`/documents/*`) require an `X-API-Key` header, set through the
`API_KEY` environment variable. Generate one with `openssl rand -hex 32`.

Query endpoints are rate limited per client. `/health` is unauthenticated so
container health checks and orchestrators can reach it.

See `app/dependencies.py`.

## 📂 Folder Structure

```
project-1-rag-assistant/
│
├── README.md                    (this file)
├── pyproject.toml              (uv dependencies)
├── uv.lock                     (pinned versions)
├── docker-compose.yml          (Local services)
├── Dockerfile                  (Container image)
├── .env.example                (Configuration template)
├── .dockerignore
├── .gitignore
│
├── app/
│   ├── main.py                 (lifespan, routers, /health)
│   ├── config.py               (Settings + ENVIRONMENT validator)
│   ├── database.py             (engine, get_db, init_db + CREATE EXTENSION)
│   ├── dependencies.py         (require_api_key, rate_limit)
│   │
│   ├── models/
│   │   └── document.py         (Document + DocumentChunk, both classes)
│   │
│   ├── schemas/
│   │   ├── document.py         (upload / chunk responses)
│   │   ├── query.py            (search request / result)
│   │   └── chat.py             (history validation + truncation)
│   │
│   ├── services/
│   │   ├── embeddings.py       (local model, embed + embed_many)
│   │   ├── documents.py        (extract, page offsets, chunking)
│   │   ├── search.py           (the <=> query)
│   │   ├── prompt.py           (the four prompt blocks)
│   │   ├── llm.py              (OpenAI-compatible client, generate + stream)
│   │   ├── rag.py              (retrieve -> assemble -> generate)
│   │   └── cache.py            (Redis client + answer cache)
│   │
│   └── routes/
│       ├── documents.py        (upload, list, chunks, delete — admin)
│       ├── search.py           (retrieval only)
│       └── chat.py             (RAG, plain and streaming)
│
├── scripts/
│   ├── create_index.py         (IVFFlat — run AFTER ingesting)
│   └── evaluate.py             (runs the eval set, reports two metrics)
│
├── evals/
│   └── preguntas.json          (questions with known answers)
│
└── samples/
    └── sample.pdf              (Test document)
```

> **Note.** `models/` holds a single file with both classes: they reference each
> other, and splitting them forces a circular import or `TYPE_CHECKING` tricks.

## 🎓 Learning Path

### Integrating Mini Projects

| Mini | Integration in PROJECT 1 |
|------|--------------------------|
| Mini 1 | CRUD operations for documents |
| Mini 2 | Redis caching for searches |
| Mini 3 | Embedding generation |
| Mini 4 | Vector similarity search |
| Mini 5 | PDF upload & chunking |

### New Concepts

- **RAG Pattern:** Retrieval + Augmented Generation
- **Production patterns:** Error handling, logging
- **Deployment:** Docker, Cloud infrastructure
- **Monitoring:** Health checks, metrics

## 🧪 Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=app --cov-report=html

# Run specific test
pytest tests/test_rag.py::test_rag_query

# Integration test
pytest tests/test_rag.py -v -s  # Verbose + stdout
```

## 📈 Performance Optimization

### Caching Strategy

```
GET /search/query?query=X
  ├─ Check Redis: cache hit? → Return (5ms)
  ├─ Miss? Query pgvector (50-100ms)
  ├─ Call LLM (1000-2000ms)
  ├─ Store in Redis with TTL=3600
  └─ Return

Result: First query ~2s, subsequent ~5ms (400x faster!)
```

### Database Indexing

```sql
-- Vector similarity index
CREATE INDEX ix_chunks_embedding 
  ON document_chunks USING ivfflat(embedding vector_cosine_ops);

-- Metadata search
CREATE INDEX ix_chunks_metadata 
  ON document_chunks USING GIN(metadata);

-- Document lookup
CREATE INDEX ix_documents_created 
  ON documents(created_at DESC);
```

### Connection Pooling

```python
# SQLAlchemy async connection pool
engine = create_async_engine(
    DATABASE_URL,
    pool_size=20,           # Max concurrent connections
    max_overflow=10,        # Extra connections if needed
    pool_pre_ping=True,     # Verify connection before use
    echo=False
)
```

## 🚢 Deployment

### Option 1: Railway (Easy, Free Tier)

```bash
# 1. Push to GitHub
git add .
git commit -m "Project 1: Complete RAG system"
git push origin main

# 2. Connect Railway
# - Visit railway.app
# - Connect GitHub repo
# - Railway auto-detects Docker

# 3. Set environment variables
# - ANTHROPIC_API_KEY
# - DATABASE_URL (Railway creates PostgreSQL)

# 4. Deploy!
# Automatic on each push
```

**Cost:** Free for small usage, ~$5-20/month for production

### Option 2: AWS (Production)

```bash
# 1. Setup Terraform
cd infra
terraform init
terraform plan
terraform apply

# 2. Push image to ECR
aws ecr get-login-password | docker login --username AWS --password-stdin <account-id>.dkr.ecr.us-east-1.amazonaws.com
docker build -t rag-api .
docker tag rag-api:latest <account-id>.dkr.ecr.us-east-1.amazonaws.com/rag-api:latest
docker push <account-id>.dkr.ecr.us-east-1.amazonaws.com/rag-api:latest

# 3. Deploy with GitHub Actions
# Automatic on each push (configured in .github/workflows/deploy.yml)
```

**Cost:** ~$50-200/month (RDS + ECS)

## 📊 Monitoring & Logging

### Health Check

```bash
GET /health

Response:
{
  "status": "ok",
  "database": "connected",
  "redis": "connected",
  "timestamp": "2024-01-15T10:00:00Z"
}
```

### Structured Logging

```python
# All logs are JSON (machine-readable)
logger.info("Document uploaded", extra={
    "document_id": "doc-123",
    "filename": "paper.pdf",
    "chunks": 42
})

# Output: {"timestamp": "...", "level": "INFO", "message": "...", "document_id": "..."}
```

### Metrics to Track

- ✅ API response time
- ✅ Cache hit ratio
- ✅ Vector search performance
- ✅ LLM latency
- ✅ Error rates
- ✅ Database connections

## 🖥️ Optional: A Frontend

**Not part of the scope.** This project is an API — `curl` and `/docs` are enough
to exercise every endpoint. Skip this section unless you want something to show.

If you do add one, note that `POST /search/query` **streams** the LLM answer.
That single fact rules out the classic server-rendered approach: you cannot dribble
tokens into a Jinja2 template that was already rendered in one shot.

### Option 1 — One HTML file + `fetch` ← recommended

No `npm`, no build step, ~80 lines. Read the stream with the browser's Streams API
and paint tokens as they arrive:

```python
# app/main.py
from fastapi.responses import FileResponse

@app.get("/")
async def ui():
    return FileResponse("static/index.html")
```

```javascript
// static/index.html — the part that matters
const res = await fetch("/rag/query", {
  method: "POST",
  headers: {"Content-Type": "application/json"},
  body: JSON.stringify({query: input.value}),
});

const reader = res.body.getReader();
const decoder = new TextDecoder();
while (true) {
  const {done, value} = await reader.read();
  if (done) break;
  output.textContent += decoder.decode(value, {stream: true});
}
```

**Why this one:** consuming a `StreamingResponse` end to end is genuinely part of
what this project teaches. A frontend toolchain is not.

### Option 2 — A real SPA (React + Vite)

Since **FastAPI 0.138.0** (June 2026) there is a first-class way to serve a built
SPA:

```python
app.frontend("/", directory="dist")
```

It replaces the old `mount(StaticFiles(html=True))` + catch-all hack, and gets the
fallback right: a missing asset returns **404**, while a missing *page* falls back
to `index.html` so the client router can handle it. With the old hack a missing
`.js` returned HTML, and the browser choked parsing it.

Later versions added dependencies in `frontend()` (0.139.0, e.g. cookie auth) and
`check_dir="auto"` for `fastapi dev` (0.141.0).

**The cost:** a whole frontend toolchain in a backend roadmap. Worth it only if you
want this in a portfolio.

### Option 3 — Jinja2 templates

Fits poorly here, precisely because of streaming. Mentioned only so you know it was
considered and rejected.

## 🎯 What Makes This Production-Ready

✅ **Async everywhere** (FastAPI, SQLAlchemy, Redis)  
✅ **Proper error handling** (HTTPException, try-catch)  
✅ **Caching layer** (Redis with TTL)  
✅ **Vector indexing** (IVFFlat for speed)  
✅ **Connection pooling** (Reuse DB connections)  
✅ **Structured logging** (JSON format)  
✅ **Health checks** (Kubernetes-ready)  
✅ **CI/CD pipeline** (Automated deployment)  
✅ **Infrastructure as Code** (Terraform)  
✅ **Comprehensive tests** (Unit + integration)  

## 📚 Related Concepts

### RAG Pattern

```
Traditional QA:
  Question → LLM → Generic Answer

RAG:
  Question → Search Docs → Retrieve Context → LLM (with context) → Specific Answer
  
Benefit: Answers are grounded in your documents
```

### Vector Search

```
Text similarity without regex/keywords

Traditional: "machine" ≠ "ML" (different strings)
Vector: Embed both → Similar vectors → Found!
```

### Chunking Strategy

```
Why? LLM context window is limited
How? Split large docs into 1000-2000 char chunks
Smart? Overlap chunks to preserve context
```

## ❓ Troubleshooting

### Database Connection Issues

```bash
# Check PostgreSQL is running
docker compose logs postgres

# Verify pgvector extension
docker compose exec postgres psql -U postgres -d rag_db \
  -c "CREATE EXTENSION IF NOT EXISTS vector;"

# Test connection
uv run python -c "
from app.database import init_db
import asyncio
asyncio.run(init_db())
print('✅ Database ready')
"
```

### Embedding Generation Errors

Embeddings are generated **locally** by `sentence-transformers` (Mini 3), not by
an API — `ANTHROPIC_API_KEY` is only for the answer-generation step. A failure
here is a model-loading problem, not an auth problem.

```bash
# The model is downloaded on FIRST USE and cached in ~/.cache/huggingface.
# No network on first run = failure here.
ls ~/.cache/huggingface/hub

# Test embedding service
uv run python -c "
from app.services.embeddings import embedding_service
import asyncio
result = asyncio.run(embedding_service.embed('test'))
print(f'✅ Embedding generated: {len(result)} dimensions')
"
```

### Vector Search Returns No Results

```bash
# Verify embeddings are stored
docker compose exec postgres psql -U postgres -d rag_db -c \
  "SELECT COUNT(*) FROM document_chunks WHERE embedding IS NOT NULL;"

# Should show count > 0

# Check index exists
docker compose exec postgres psql -U postgres -d rag_db -c \
  "SELECT * FROM pg_indexes WHERE tablename = 'document_chunks';"
```

## 📖 Documentation

- **[architecture.md](./docs/architecture.md)** - System design details
- **[api.md](./docs/api.md)** - Complete API reference
- **[deployment.md](./docs/deployment.md)** - Deploy to production

## 🔗 Resources

- [FastAPI Best Practices](https://fastapi.tiangolo.com/deployment/concepts/)
- [SQLAlchemy Async](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- [pgvector Documentation](https://github.com/pgvector/pgvector)
- [RAG Papers](https://arxiv.org/abs/2005.11401)
- [Terraform AWS](https://registry.terraform.io/providers/hashicorp/aws/latest/docs)

## ⏱️ Timeline

| Phase | Time | Tasks |
|-------|------|-------|
| **Integration** | 3-4h | Combine Mini 1-5 code |
| **Testing** | 2-3h | Unit + integration tests |
| **Polish** | 2-3h | Error handling, logging, docs |
| **Deploy** | 1-2h | Railway or AWS |
| **Total** | 10-15h | Complete project |

## ✅ Completion Checklist

### Code Quality
- [ ] All endpoints tested
- [ ] Error handling complete
- [ ] Logging structured (JSON)
- [ ] Comments on complex logic

### Documentation
- [ ] README complete
- [ ] API docs (docstrings)
- [ ] Architecture diagram
- [ ] Deployment guide

### Testing
- [ ] Unit tests (90%+ coverage)
- [ ] Integration tests
- [ ] Load test (basic)
- [ ] Error scenarios tested

### Deployment
- [ ] Docker image works
- [ ] Environment variables set
- [ ] Database migrations done
- [ ] Health check passes
- [ ] Deployed to Railway/AWS

### GitHub
- [ ] All code pushed
- [ ] README visible
- [ ] Sample documents included
- [ ] Issue templates setup

### Optional (not required to consider this done)
- [ ] Frontend — see [Optional: A Frontend](#-optional-a-frontend)

## 📊 Expected Metrics (Production)

```
Throughput:
- Document upload: <5 seconds (100MB PDF)
- Search query: <2 seconds (first time)
- Search query: <100ms (cached)

Accuracy:
- Vector search relevance: 85%+
- LLM answer quality: 90%+

Availability:
- Uptime: 99.9%+
- Response time p95: <3 seconds
```

## 🎯 After Completion

### Portfolio
- ✅ GitHub repo with 150+ potential ⭐
- ✅ Production-ready code
- ✅ Complete documentation
- ✅ Real-world use case

### Interview Ready
- ✅ Talk about RAG architecture
- ✅ Explain vector search
- ✅ Discuss production patterns
- ✅ Show deployment knowledge

### Next Steps
1. **System Design prep:** Study scaling this for 1M users
2. **Job applications:** Use this as portfolio project
3. **Project 2:** Start agentic backend (another portfolio piece)

## 📞 Support

- 📖 Check docs/ folder
- 🐛 See TROUBLESHOOTING section above
- 💬 Review code comments
- 📝 Read docstrings

---

## Summary

**PROJECT 1: RAG Research Assistant**

| Aspect | Value |
|--------|-------|
| Integration | Mini 1-5 |
| Lines of Code | ~2000 |
| API Endpoints | 8-10 |
| Database Tables | 2 (documents, chunks) |
| Deploy Time | <5 min (Railway) |
| Complexity | Intermediate |
| Portfolio Value | ⭐⭐⭐⭐ (150+ stars) |
| Interview Value | 🔥 Very High |

---

**Made as part of Sr Backend Roadmap** 🚀

Start: After Mini 1-5 complete  
Duration: 10-15 hours  
Result: Production-ready RAG system + portfolio project