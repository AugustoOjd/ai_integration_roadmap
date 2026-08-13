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
│  POST /rag/query                            │
│    └─ Full RAG pipeline (all above)         │
│                                             │
└─────────────────────────────────────────────┘
        ↓              ↓              ↓
   PostgreSQL       Redis          Anthropic
   (pgvector)       (cache)        (LLM + embeddings)
```

## 📚 Tech Stack

### Core
- **FastAPI** 0.109+ - Web framework
- **Python** 3.11+ - Runtime
- **Uvicorn** - ASGI server

### Database & Storage
- **PostgreSQL** 16 - Primary database
- **pgvector** - Vector storage & search
- **Redis** 7+ - Caching layer
- **SQLAlchemy** 2.0+ - Async ORM

### AI/LLM
- **Anthropic Claude** - LLM for answers
- **LangChain** - Optional utilities
- **Embeddings** - Vector representation

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
Python 3.11+
Poetry
Docker + Docker Compose
ANTHROPIC_API_KEY=sk-ant-...
```

### Local Setup

```bash
# 1. Clone/navigate to project
cd project-1-rag-assistant

# 2. Install dependencies
poetry install

# 3. Setup environment
cp .env.example .env
# Edit .env with your ANTHROPIC_API_KEY

# 4. Start services
docker-compose up -d

# Verify database is ready
docker-compose logs postgres | grep "ready"

# 5. Run migrations (if using Alembic)
poetry run alembic upgrade head

# 6. Start app
poetry run uvicorn app.main:app --reload

# 7. Test
curl http://localhost:8000/health
curl http://localhost:8000/docs  # Interactive API docs
```

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

### Semantic Search

```bash
# Simple search
POST /search/query
{
  "query": "What is machine learning?",
  "top_k": 5
}

Response:
{
  "query": "What is machine learning?",
  "results": [
    {
      "filename": "document.pdf",
      "chunk": "Machine learning is...",
      "similarity": 0.89
    }
  ]
}

# Streaming search
POST /search/query/stream
{
  "query": "...",
  "top_k": 5
}

Response: Server-Sent Events (SSE) stream
```

### RAG (Full Pipeline)

```bash
# Complete RAG query
POST /rag/query
{
  "query": "Summarize the main findings",
  "top_k": 5
}

Response:
{
  "query": "Summarize the main findings",
  "relevant_documents": [
    {
      "filename": "...",
      "chunk": "...",
      "similarity": 0.92
    }
  ],
  "answer": "Based on the documents, the main findings are..."
}
```

## 📂 Folder Structure

```
project-1-rag-assistant/
│
├── README.md                    (this file)
├── pyproject.toml              (Poetry dependencies)
├── docker-compose.yml          (Local services)
├── Dockerfile                  (Container image)
├── .env.example                (Configuration template)
├── .dockerignore
├── .gitignore
│
├── .github/
│   └── workflows/
│       └── deploy.yml          (CI/CD pipeline)
│
├── infra/                      (Infrastructure as Code)
│   ├── main.tf                 (AWS configuration)
│   ├── variables.tf
│   └── outputs.tf
│
├── app/
│   ├── __init__.py
│   ├── main.py                 (FastAPI app entry)
│   ├── config.py               (Settings & validation)
│   ├── database.py             (DB connection)
│   │
│   ├── models/                 (SQLAlchemy models)
│   │   ├── __init__.py
│   │   ├── document.py         (Document table)
│   │   └── chunk.py            (DocumentChunk table)
│   │
│   ├── schemas/                (Pydantic schemas)
│   │   ├── __init__.py
│   │   ├── document.py
│   │   └── query.py
│   │
│   ├── services/               (Business logic)
│   │   ├── __init__.py
│   │   ├── embeddings.py       (Vector generation)
│   │   ├── documents.py        (PDF processing)
│   │   ├── cache.py            (Redis caching)
│   │   └── rag.py              (RAG orchestration)
│   │
│   ├── routes/                 (API endpoints)
│   │   ├── __init__.py
│   │   ├── documents.py        (Upload, list)
│   │   ├── search.py           (Search endpoints)
│   │   └── rag.py              (RAG endpoint)
│   │
│   └── utils/                  (Utilities)
│       ├── __init__.py
│       ├── logging.py          (Structured logging)
│       └── decorators.py       (Custom decorators)
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py             (Pytest fixtures)
│   ├── test_documents.py
│   ├── test_search.py
│   └── test_rag.py
│
├── docs/
│   ├── architecture.md         (System design)
│   ├── api.md                  (API documentation)
│   └── deployment.md           (Deploy guides)
│
└── samples/
    └── sample.pdf              (Test document)
```

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
docker-compose logs postgres

# Verify pgvector extension
docker-compose exec postgres psql -U postgres -d rag_db \
  -c "CREATE EXTENSION IF NOT EXISTS vector;"

# Test connection
poetry run python -c "
from app.database import init_db
import asyncio
asyncio.run(init_db())
print('✅ Database ready')
"
```

### Embedding Generation Errors

```bash
# Check API key
echo $ANTHROPIC_API_KEY

# Test embedding service
poetry run python -c "
from app.services.embeddings import embedding_service
import asyncio
result = asyncio.run(embedding_service.embed_text('test'))
print(f'✅ Embedding generated: {len(result)} dimensions')
"
```

### Vector Search Returns No Results

```bash
# Verify embeddings are stored
docker-compose exec postgres psql -U postgres -d rag_db -c \
  "SELECT COUNT(*) FROM document_chunks WHERE embedding IS NOT NULL;"

# Should show count > 0

# Check index exists
docker-compose exec postgres psql -U postgres -d rag_db -c \
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