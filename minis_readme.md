# 📋 README.md Templates para Cada Mini Proyecto
 
Copia estos en cada carpeta mini-X-nombre/
 
---
 
# MINI 1: CRUD API
 
Nombre: `mini-1-crud-api/README.md`
 
````markdown
# 🚀 Mini 1: FastAPI + PostgreSQL CRUD
 
Simple CRUD API using FastAPI and PostgreSQL async.
 
## 🎯 Learning Objectives
 
- ✅ FastAPI routing and async patterns
- ✅ SQLAlchemy async with PostgreSQL
- ✅ Pydantic schemas (request/response)
- ✅ Dependency injection
- ✅ Error handling (HTTPException)
- ✅ Database connection pooling
- ✅ Deploy to Railway
 
## 🏗️ Architecture
 
````
FastAPI Routes
    ↓
Pydantic Schemas (validation)
    ↓
SQLAlchemy ORM (async)
    ↓
PostgreSQL Database
````
 
## 📚 Tech Stack
 
- **FastAPI** 0.109+ - Web framework
- **SQLAlchemy** 2.0+ - Async ORM
- **PostgreSQL** 16 - Database
- **Pydantic** V2 - Data validation
- **Docker** - Containerization
 
## 🚀 Quick Start
 
### Prerequisites
```bash
Python 3.11+
uv
Docker + Docker Compose
```
 
### Setup
 
```bash
# 1. Install dependencies
uv sync
 
# 2. Start database
docker-compose up -d
 
# 3. Run app
uv run uvicorn app.main:app --reload
 
# 4. Test
curl http://localhost:8000/health
```
 
## 📝 API Endpoints
 
```bash
# List notes
GET /notes/
 
# Create note
POST /notes/
{
  "title": "My Note",
  "content": "Hello World"
}
 
# Get single note
GET /notes/{note_id}
 
# Update note
PUT /notes/{note_id}
{
  "title": "Updated",
  "content": "New content"
}
 
# Delete note
DELETE /notes/{note_id}
```
 
## 📂 Folder Structure
 
````
mini-1-crud-api/
├── app/
│   ├── main.py          # FastAPI app
│   ├── config.py        # Settings
│   ├── database.py      # DB connection
│   ├── models/
│   │   └── note.py      # SQLAlchemy model
│   ├── schemas/
│   │   └── note.py      # Pydantic schemas
│   └── routes/
│       └── notes.py     # API endpoints
├── tests/
│   └── test_notes.py
├── docker-compose.yml
├── Dockerfile
└── pyproject.toml
````
 
## 🧪 Testing
 
```bash
# Run all tests
pytest
 
# Run with coverage
pytest --cov=app
```
 
## 📈 What You'll Learn
 
### FastAPI
- Route decorators (@app.get, @app.post, etc)
- Path parameters and query strings
- Request body validation
- Response models
- Dependency injection (Depends)
- Status codes and error handling
 
### SQLAlchemy Async
- Engine creation with asyncio
- AsyncSession management
- Column types and constraints
- Primary keys and timestamps
- Query execution (select, where, order_by)
 
### Database
- Creating tables
- CRUD operations
- Migrations (basic)
- Connection pooling
 
### Deployment
- Docker containerization
- Environment configuration
- Railway deployment
 
## 🎓 Key Concepts
 
**Async/Await:**
```python
async def get_notes(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Note))
    return result.scalars().all()
```
 
**Dependency Injection:**
```python
async def get_db():
    async with async_session() as session:
        yield session
 
# Used in routes
@router.get("/")
async def list_notes(db: AsyncSession = Depends(get_db)):
    ...
```
 
**Pydantic Validation:**
```python
class NoteCreate(BaseModel):
    title: str  # Required
    content: str  # Required
 
class NoteResponse(BaseModel):
    id: str
    title: str
    content: str
    created_at: datetime
```
 
## 🚢 Deploy to Railway
 
1. Push to GitHub
2. Connect Railway to repo
3. Set DATABASE_URL env var
4. Deploy! 🎉
 
## ❓ Troubleshooting
 
**Port 5432 already in use?**
```bash
docker-compose down
# or change port in docker-compose.yml
```
 
**SQLAlchemy errors?**
```bash
# Make sure async driver is installed
uv sync
```
 
**Cannot connect to DB?**
```bash
# Check database is running
docker-compose ps
 
# Check logs
docker-compose logs postgres
```
 
## 📚 Resources
 
- [FastAPI Docs](https://fastapi.tiangolo.com)
- [SQLAlchemy Async](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- [Pydantic V2](https://docs.pydantic.dev/latest/)
- [PostgreSQL](https://www.postgresql.org/docs/)
 
## ⏱️ Timeline
 
- Setup: 30 min
- Coding: 2 hours
- Testing: 30 min
- Deploy: 15 min
- **Total: 3-4 hours**
 
## ✅ Checklist
 
- [ ] Install dependencies
- [ ] Start PostgreSQL
- [ ] Create database models
- [ ] Create Pydantic schemas
- [ ] Create routes (POST, GET, PUT, DELETE)
- [ ] Test all endpoints
- [ ] Deploy to Railway
- [ ] Share on GitHub
 
## 🎯 Next: Mini 2
 
Ready for Redis caching? Go to `../mini-2-redis-cache/`
 
---
 
**Made as part of Sr Backend Roadmap** 🚀
````
 
---
 
# MINI 2: Redis Caching
 
Nombre: `mini-2-redis-cache/README.md`
 
````markdown
# 🔴 Mini 2: Redis Caching
 
Add Redis caching layer to Mini 1 for performance boost.
 
## 🎯 Learning Objectives
 
- ✅ Redis connection and commands
- ✅ Cache-aside pattern
- ✅ Key expiration (TTL)
- ✅ Cache invalidation
- ✅ Performance optimization
- ✅ Conditional caching (if modified)
 
## 🏗️ Architecture
 
````
Request
    ↓
Check Redis cache
    ↓ (HIT)
Return cached data
    ↓ (MISS)
Query PostgreSQL
    ↓
Store in Redis
    ↓
Return to client
````
 
## 📚 Tech Stack
 
- **FastAPI** - Web framework
- **PostgreSQL** - Primary DB
- **Redis** - Caching layer
- **aioredis** - Async Redis client
- **Docker Compose** - Orchestration
 
## 🚀 Quick Start
 
```bash
# 1. Copy from Mini 1
cp -r ../mini-1-crud-api/* .
 
# 2. Add Redis
uv add redis
 
# 3. Update docker-compose.yml
# Add redis service (see template)
 
# 4. Start services
docker-compose up -d
 
# 5. Run app
uv run uvicorn app.main:app --reload
```
 
## 📊 Caching Strategy
 
### Cache-Aside Pattern
 
```python
# Check cache
cached = await cache.get("notes:all")
if cached:
    return cached
 
# Query DB if miss
notes = await db.execute(select(Note))
 
# Store in cache
await cache.set("notes:all", notes, ttl=3600)
 
return notes
```
 
### TTL (Time To Live)
 
```python
# Cache expires after 1 hour
await cache.set(key, value, ttl=3600)
 
# After 3600 seconds, Redis deletes key automatically
```
 
### Cache Invalidation
 
```python
# When creating/updating/deleting, clear cache
await cache.delete("notes:all")
await cache.delete(f"note:{note_id}")
```
 
## 🔑 Redis Keys Pattern
 
````
notes:all                    # List all notes
note:{id}                    # Single note
search:query:{query}         # Search results
user:{user_id}:settings      # User settings
session:{session_id}         # Session data
````
 
## 🧪 Testing Performance
 
```bash
# Time first request (cache miss)
time curl http://localhost:8000/notes/
# Output: ~100ms
 
# Time second request (cache hit)
time curl http://localhost:8000/notes/
# Output: ~5ms (20x faster!)
```
 
## 📈 Concepts
 
**Redis Data Types:**
- **String** - Key → Value
- **Hash** - Key → {field → value}
- **List** - Key → [values]
- **Set** - Key → {unique values}
- **Sorted Set** - Key → {value, score}
 
**For this mini:** String (simplest)
 
## 📂 Folder Structure
 
````
mini-2-redis-cache/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   ├── models/
│   │   └── note.py
│   ├── schemas/
│   │   └── note.py
│   ├── services/
│   │   └── cache.py          # NEW: Cache logic
│   └── routes/
│       └── notes.py           # UPDATED: Add cache
├── tests/
│   └── test_cache.py          # NEW: Cache tests
├── docker-compose.yml         # UPDATED: Add Redis
└── pyproject.toml             # UPDATED: Add redis
````
 
## 💾 Redis Commands Reference
 
```bash
# Inside container or redis-cli
docker-compose exec redis redis-cli
 
# Get key
GET mykey
 
# Set key with expiry
SET mykey "value" EX 3600
 
# Delete key
DEL mykey
 
# Get all keys
KEYS *
 
# Clear all
FLUSHDB
 
# Monitor commands
MONITOR
```
 
## ⚡ Performance Metrics
 
**Before caching:**
- List all notes: ~100-200ms
- Get single note: ~50-100ms
 
**After caching:**
- List all notes (hit): ~5-10ms (20-40x faster!)
- Get single note (hit): ~2-5ms (25-50x faster!)
 
## 🎓 Key Concepts
 
**Async Redis:**
```python
import redis.asyncio as redis
 
client = await redis.from_url("redis://localhost:6379")
value = await client.get("key")
await client.set("key", value, ex=3600)
```
 
**JSON in Redis:**
```python
# Store Python dict as JSON
import json
 
data = {"name": "John", "age": 30}
await client.set("user:1", json.dumps(data))
 
# Retrieve and parse
raw = await client.get("user:1")
parsed = json.loads(raw)
```
 
## 📈 Cache Hit Ratio
 
Track performance:
```python
# In production
cache_hits = 0
cache_misses = 0
 
# Calculate
hit_ratio = cache_hits / (cache_hits + cache_misses)
# Goal: 80%+ hit ratio
```
 
## 🚢 Deploy
 
```bash
# Push to GitHub
git add .
git commit -m "Mini 2: Redis caching"
git push
 
# Railway will detect Redis and PostgreSQL
# Just set environment variables
```
 
## ❓ Troubleshooting
 
**Cannot connect to Redis?**
```bash
docker-compose logs redis
docker-compose restart redis
```
 
**Keys not expiring?**
```bash
# Check TTL
docker-compose exec redis redis-cli TTL mykey
# Should be positive number (seconds remaining)
```
 
**Cache not working?**
```bash
# Check if data is in Redis
docker-compose exec redis redis-cli KEYS "*"
# Should show keys
```
 
## 📚 Resources
 
- [Redis Documentation](https://redis.io/docs/)
- [Redis Commands](https://redis.io/commands/)
- [redis-py (Python client)](https://github.com/redis/redis-py)
- [Cache Patterns](https://codeahoy.com/2017/08/11/caching-strategies-and-patterns/)
 
## ⏱️ Timeline
 
- Setup: 20 min
- Add Redis service: 15 min
- Implement cache: 1 hour
- Test performance: 30 min
- **Total: 2-3 hours**
 
## ✅ Checklist
 
- [ ] Add Redis to docker-compose
- [ ] Create cache.py service
- [ ] Update routes to use cache
- [ ] Test cache hits/misses
- [ ] Measure performance improvement
- [ ] Push to GitHub
 
## 🎯 Next: Mini 3
 
Ready for embeddings? Go to `../mini-3-embeddings/`
 
---
 
**Made as part of Sr Backend Roadmap** 🚀
````
 
---
 
# MINI 3: Embeddings
 
Nombre: `mini-3-embeddings/README.md`
 
````markdown
# 🧮 Mini 3: Embeddings Basics
 
Generate and compare embeddings (vector representations of text).
 
## 🎯 Learning Objectives
 
- ✅ What are embeddings
- ✅ Vector math (distance, similarity)
- ✅ Cosine similarity calculation
- ✅ Normalization
- ✅ Dimensionality concepts
- ✅ LLM embeddings API
 
## 📚 What Are Embeddings?
 
Embeddings convert text into vectors (arrays of numbers).
 
````
Text: "python is a programming language"
    ↓
Embedding: [-0.23, 0.45, 0.12, ..., 0.78]  (1536 dimensions)
    ↓
Properties:
- Each dimension represents semantic meaning
- Similar texts = similar vectors
- Distance between vectors = semantic similarity
````
 
## 🏗️ Architecture
 
````
Text Input
    ↓
Embedding Model
    ↓
Vector (1536-D)
    ↓
Store or Compare
````
 
## 📚 Tech Stack
 
- **FastAPI** - Web framework
- **Anthropic Claude** - Embedding generation
- **NumPy** - Vector math
- **Pydantic** - Data validation
 
## 🚀 Quick Start
 
```bash
# 1. Install dependencies
uv add anthropic numpy
 
# 2. Create .env
export ANTHROPIC_API_KEY=sk-ant-...
 
# 3. Run app
uv run uvicorn app.main:app --reload
```
 
## 📝 API Endpoints
 
```bash
# Generate embedding for text
POST /embeddings/embed
{
  "text": "Python is awesome"
}
 
Response:
{
  "text": "Python is awesome",
  "embedding": [-0.23, 0.45, ..., 0.78],  # 1536 numbers
  "dimension": 1536
}
 
# Compare similarity
POST /embeddings/similarity
{
  "text1": "python",
  "text2": "programming"
}
 
Response:
{
  "text1": "python",
  "text2": "programming",
  "similarity": 0.75  # 0-1 scale, 1=identical
}
```
 
## 📊 Vector Similarity
 
### Cosine Similarity
 
````
Similarity = (A · B) / (||A|| * ||B||)
 
Where:
- A · B = dot product
- ||A|| = magnitude of A
- ||B|| = magnitude of B
Range: -1 to 1 (typically 0 to 1 for normalized)
- 1.0 = identical
- 0.5 = somewhat similar
- 0.0 = unrelated
````
 
## 🧪 Examples
 
```python
# Get embeddings
emb1 = embed("cat")      # [-0.2, 0.3, ..., 0.1]
emb2 = embed("dog")      # [-0.19, 0.29, ..., 0.11]
emb3 = embed("bicycle")  # [0.5, -0.3, ..., 0.8]
 
# Calculate similarities
similarity(emb1, emb2) → 0.95  # Cat and dog are similar
similarity(emb1, emb3) → 0.15  # Cat and bicycle are different
```
 
## 🎓 Key Concepts
 
**Embedding Dimension:**
- 1536D for Claude embeddings
- Higher = more expressive but slower
- 128D to 3072D common range
 
**Normalization:**
```python
# Important for accurate similarity
def normalize(embedding):
    norm = np.linalg.norm(embedding)
    return embedding / norm
```
 
**Distance Metrics:**
- Cosine: Best for embeddings
- Euclidean: Alternative but slower
- Manhattan: Rarely used
 
## 📂 Folder Structure
 
````
mini-3-embeddings/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── services/
│   │   └── embeddings.py      # Core logic
│   ├── schemas/
│   │   └── embedding.py       # Request/response
│   └── routes/
│       └── embeddings.py      # Endpoints
├── tests/
│   └── test_embeddings.py
└── pyproject.toml
````
 
## 🔬 Testing Similarity
 
```bash
# Test identical texts
curl -X POST http://localhost:8000/embeddings/similarity \
  -H "Content-Type: application/json" \
  -d '{
    "text1": "hello",
    "text2": "hello"
  }'
# Response: similarity = 1.0
 
# Test different texts
curl -X POST http://localhost:8000/embeddings/similarity \
  -d '{
    "text1": "cat",
    "text2": "dog"
  }'
# Response: similarity ≈ 0.8
 
# Test unrelated texts
curl -X POST http://localhost:8000/embeddings/similarity \
  -d '{
    "text1": "cat",
    "text2": "bicycle"
  }'
# Response: similarity ≈ 0.1
```
 
## 📈 Performance
 
- Generation: ~200-500ms per text
- Similarity: ~1ms (vector math only)
- Batch: More efficient than individual calls
 
## 💾 Storage (Preview)
 
In Mini 4, you'll store embeddings in PostgreSQL:
````
Text: "Python is a language"
Embedding: [1536 numbers]
    ↓
Store in database
    ↓
Query with similarity search
````
 
## 🚢 Deploy
 
```bash
git add .
git commit -m "Mini 3: Embeddings"
git push
```
 
## ❓ Troubleshooting
 
**ANTHROPIC_API_KEY not working?**
```bash
# Check .env
cat .env | grep ANTHROPIC
 
# Test directly
python -c "from anthropic import Anthropic; print('OK')"
```
 
**Different embeddings for same text?**
````
This shouldn't happen. Embeddings are deterministic.
If it does, check your hashing method (if using local generation).
````
 
## 📚 Resources
 
- [What are embeddings?](https://platform.openai.com/docs/guides/embeddings)
- [Cosine Similarity](https://en.wikipedia.org/wiki/Cosine_similarity)
- [Vector Databases](https://www.pinecone.io/learn/vector-database/)
- [Anthropic Embeddings](https://docs.anthropic.com)
 
## ⏱️ Timeline
 
- Setup: 20 min
- Core logic: 1 hour
- API endpoints: 45 min
- Testing: 30 min
- **Total: 2-3 hours**
 
## ✅ Checklist
 
- [ ] Install dependencies
- [ ] Create embedding service
- [ ] Test embedding generation
- [ ] Implement similarity calculation
- [ ] Create API endpoints
- [ ] Test embeddings and similarity
- [ ] Push to GitHub
 
## 🎯 Next: Mini 4
 
Ready for vector search? Go to `../mini-4-pgvector/`
 
---
 
**Made as part of Sr Backend Roadmap** 🚀
````
 
---
 
# MINI 4: pgvector Search
 
Nombre: `mini-4-pgvector/README.md`
 
````markdown
# 🔍 Mini 4: pgvector Semantic Search
 
Store embeddings in PostgreSQL and search by similarity.
 
## 🎯 Learning Objectives
 
- ✅ pgvector PostgreSQL extension
- ✅ Storing vectors in database
- ✅ Vector similarity operators
- ✅ Index types (IVFFlat)
- ✅ Semantic search queries
- ✅ Performance optimization
 
## 🏗️ Architecture
 
````
Text Query
    ↓
Generate embedding
    ↓
Vector similarity search in pgvector
    ↓
Return top-K results
````
 
## 📚 Tech Stack
 
- **PostgreSQL 16** - with pgvector extension
- **pgvector** - Vector storage
- **FastAPI** - Web framework
- **SQLAlchemy** - ORM with pgvector support
- **Docker Compose** - Stack
 
## 🚀 Quick Start
 
```bash
# 1. Start PostgreSQL with pgvector
docker-compose up -d
 
# 2. Install dependencies
uv sync
 
# 3. Run app
uv run uvicorn app.main:app --reload
```
 
## 📝 API Endpoints
 
```bash
# Create note with embedding
POST /notes/
{
  "title": "Python Tips",
  "content": "Python is a powerful language"
}
 
# Search semantically
POST /notes/search
{
  "query": "programming languages",
  "top_k": 5
}
 
Response:
[
  {
    "id": "note-1",
    "title": "Python Tips",
    "content": "Python is a powerful language",
    "similarity": 0.85
  }
]
```
 
## 🗄️ Database Schema
 
```sql
CREATE TABLE notes (
  id UUID PRIMARY KEY,
  title VARCHAR(200),
  content TEXT,
  embedding vector(1536),  -- NEW: Vector column
  created_at TIMESTAMP
);
 
-- INDEX for faster search
CREATE INDEX ix_notes_embedding 
  ON notes USING ivfflat(embedding vector_cosine_ops);
```
 
## 📊 pgvector Operators
 
```sql
-- Cosine similarity (most common)
SELECT * FROM notes
ORDER BY embedding <-> query_embedding
LIMIT 5;
 
-- Euclidean distance
ORDER BY embedding <=> query_embedding
 
-- Inner product
ORDER BY embedding <#> query_embedding
 
-- L2 distance
ORDER BY embedding <-> query_embedding
```
 
## 🎓 Key Concepts
 
**Vector Operators:**
```python
# In SQL:
# <->  = cosine distance (preferred)
# <=>  = euclidean distance
# <#>  = inner product
```
 
**Distance to Similarity:**
```python
# Convert distance to similarity (0-1)
similarity = 1 - distance
 
# Example:
# distance = 0.2 → similarity = 0.8 (80% similar)
# distance = 0.9 → similarity = 0.1 (10% similar)
```
 
## 🧪 Testing Search
 
```bash
# Create some notes
curl -X POST http://localhost:8000/notes/ \
  -d '{"title":"Python","content":"Python programming language"}'
 
curl -X POST http://localhost:8000/notes/ \
  -d '{"title":"JavaScript","content":"JavaScript for web"}'
 
# Search
curl -X POST http://localhost:8000/notes/search \
  -d '{"query":"code language","top_k":5}'
 
# Results sorted by similarity
```
 
## 📈 Index Types
 
**IVFFlat (Inverted File Flat):**
- Fast approximate search
- Good for large datasets
- ~90% accuracy
- Recommended for this use case
 
**HNSW (Hierarchical Navigable Small World):**
- Faster than IVFFlat
- More memory
- ~95% accuracy
- PostgreSQL 15+
 
**No Index (Brute Force):**
- Exact results
- Slow for large datasets
- Good for <1000 vectors
 
## 💡 Query Example
 
```python
# Search implementation
search_query = """
SELECT 
  id,
  title,
  content,
  (1 - (embedding <-> :embedding)) as similarity
FROM notes
WHERE embedding IS NOT NULL
ORDER BY embedding <-> :embedding
LIMIT :top_k
"""
 
result = await db.execute(
  text(search_query),
  {
    "embedding": str(query_embedding),
    "top_k": 5
  }
)
```
 
## 📂 Folder Structure
 
````
mini-4-pgvector/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   ├── models/
│   │   └── note.py              # UPDATED: Add embedding column
│   ├── services/
│   │   ├── embeddings.py        # From Mini 3
│   │   └── search.py            # NEW: Search logic
│   ├── routes/
│   │   └── search.py            # NEW: Search endpoints
│   └── schemas/
│       └── note.py
├── tests/
│   └── test_search.py
├── docker-compose.yml           # UPDATED: pgvector image
└── pyproject.toml               # UPDATED: Add pgvector
````
 
## 🔧 Setup pgvector
 
```bash
# docker-compose.yml uses pgvector image
image: pgvector/pgvector:pg16
 
# Enable in code
async def init_db():
    async with engine.begin() as conn:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        await conn.run_sync(Base.metadata.create_all)
```
 
## ⚡ Performance Tips
 
1. **Add Index:**
```sql
CREATE INDEX ix_embedding ON notes 
USING ivfflat(embedding vector_cosine_ops);
```
 
2. **Use WHERE clause:**
```sql
SELECT * FROM notes
WHERE created_at > now() - interval '7 days'
ORDER BY embedding <-> query_embedding
LIMIT 10;
```
 
3. **Batch searches:**
- Process multiple queries together
- Reuse connection pool
 
## 📊 Benchmark
 
````
Setup: 10,000 notes, 1536-D embeddings
 
Search without index:  ~500-800ms (full table scan)
Search with IVFFlat:   ~10-50ms   (50x faster!)
Search with HNSW:      ~5-20ms    (100x faster!)
````
 
## 🚢 Deploy
 
```bash
git add .
git commit -m "Mini 4: pgvector semantic search"
git push
```
 
## ❓ Troubleshooting
 
**pgvector extension not found?**
```bash
# Make sure image is pgvector/pgvector, not postgres
docker-compose down
docker-compose up -d
 
# Or manually enable
docker-compose exec postgres psql -U postgres -d mini_db \
  -c "CREATE EXTENSION vector;"
```
 
**Search slow?**
```bash
# Add index
CREATE INDEX ix_embedding ON notes 
USING ivfflat(embedding vector_cosine_ops);
```
 
**NULL embeddings?**
```bash
# Check embedding generation
SELECT id, embedding FROM notes LIMIT 5;
```
 
## 📚 Resources
 
- [pgvector GitHub](https://github.com/pgvector/pgvector)
- [Vector Similarity Search](https://supabase.com/vector)
- [Similarity Operators](https://github.com/pgvector/pgvector#vector-types)
 
## ⏱️ Timeline
 
- Setup: 30 min
- Implement search: 1.5 hours
- Testing: 45 min
- **Total: 3-4 hours**
 
## ✅ Checklist
 
- [ ] Use pgvector Docker image
- [ ] Create vector column in notes
- [ ] Implement embedding generation
- [ ] Add search endpoint
- [ ] Create similarity index
- [ ] Test search results
- [ ] Benchmark performance
- [ ] Push to GitHub
 
## 🎯 Next: Mini 5
 
Ready for PDF processing? Go to `../mini-5-pdf-processing/`
 
---
 
**Made as part of Sr Backend Roadmap** 🚀
````
 
---
 
# MINI 5: PDF Processing
 
Nombre: `mini-5-pdf-processing/README.md`
 
````markdown
# 📄 Mini 5: PDF Upload & Chunking
 
Process PDFs and prepare for embedding.
 
## 🎯 Learning Objectives
 
- ✅ File upload handling
- ✅ PDF text extraction
- ✅ Text chunking strategy
- ✅ Chunk overlap
- ✅ Metadata storage
- ✅ Multi-part form data
 
## 🏗️ Architecture
 
````
Upload PDF
    ↓
Extract text (pypdf)
    ↓
Chunk text (overlap strategy)
    ↓
Store chunks in DB
    ↓ (Next: Generate embeddings)
````
 
## 📚 Tech Stack
 
- **FastAPI** - Web framework
- **pypdf** - PDF extraction
- **python-multipart** - Form data parsing
- **PostgreSQL** - Storage
- **SQLAlchemy** - ORM
 
## 🚀 Quick Start
 
```bash
# 1. Install dependencies
uv add pypdf python-multipart
 
# 2. Start database
docker-compose up -d
 
# 3. Run app
uv run uvicorn app.main:app --reload
 
# 4. Upload a PDF
curl -X POST http://localhost:8000/documents/upload \
  -F "file=@sample.pdf"
```
 
## 📝 API Endpoints
 
```bash
# Upload document
POST /documents/upload
Files: file (PDF or text)
 
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
 
Response:
[
  {
    "id": "chunk-1",
    "chunk_text": "First 1000 characters...",
    "chunk_index": 0
  }
]
```
 
## 🧩 Chunking Strategy
 
### Why Chunk?
 
````
Problem: LLM context window is limited (~200k tokens)
Solution: Split large documents into manageable chunks
 
Tradeoff:
- Chunks too small: lose context
- Chunks too large: waste context window
- Optimal: 1000-2000 characters per chunk
````
 
### Overlap
 
````
Text: "ABCDEFGHIJ..." (100 chars)
Chunk size: 30, Overlap: 10
 
Result:
[0:30]    "ABCDEFGHIJ..."
[20:50]   "IJKLMNOPQR..."  (10 overlap)
[40:70]   "QRSTUVWXYZ..."  (10 overlap)
 
Benefit:
- Context preserved across chunks
- No information loss at boundaries
````
 
## 📂 Database Schema
 
```sql
CREATE TABLE documents (
  id UUID PRIMARY KEY,
  filename VARCHAR,
  original_text TEXT,
  created_at TIMESTAMP
);
 
CREATE TABLE document_chunks (
  id UUID PRIMARY KEY,
  document_id UUID FOREIGN KEY,
  chunk_text TEXT,
  chunk_index INTEGER,
  created_at TIMESTAMP
);
```
 
## 🧪 Test Upload
 
```bash
# Create sample PDF (or use existing)
# Then upload
curl -X POST http://localhost:8000/documents/upload \
  -F "file=@sample.pdf"
 
# Verify
curl http://localhost:8000/documents/
 
# Get chunks
curl http://localhost:8000/documents/{doc_id}/chunks
```
 
## 🎓 Key Concepts
 
**Text Extraction:**
```python
from pypdf import PdfReader
 
pdf_reader = PdfReader("document.pdf")
text = ""
for page in pdf_reader.pages:
    text += page.extract_text()
```
 
**Chunking:**
```python
def chunk_text(text, size=1000, overlap=200):
    chunks = []
    start = 0
    while start < len(text):
        end = start + size
        chunks.append(text[start:end])
        start = end - overlap  # Go back by overlap
    return chunks
```
 
**Metadata:**
```python
chunk = {
  "text": "...",
  "source": "document.pdf",
  "chunk_index": 0,
  "page_range": (0, 1)
}
```
 
## 📊 File Format Support
 
**Current:**
- PDF (.pdf)
- Plain text (.txt)
 
**Easy to extend:**
- Markdown (.md)
- Word (.docx)
- HTML (.html)
 
## 📂 Folder Structure
 
````
mini-5-pdf-processing/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   ├── models/
│   │   ├── document.py        # NEW
│   │   └── chunk.py           # NEW
│   ├── services/
│   │   └── documents.py       # NEW: Processing logic
│   ├── routes/
│   │   └── documents.py       # NEW: Upload endpoints
│   └── schemas/
│       └── document.py        # NEW
├── tests/
│   └── test_documents.py
├── samples/
│   └── sample.pdf             # Test file
└── pyproject.toml
````
 
## 🧪 Testing
 
```bash
pytest tests/test_documents.py
 
# Test with actual PDF
uv run pytest -v
```
 
## 📈 Performance
 
**Processing times (for 10-page PDF):**
- Extraction: ~500ms
- Chunking: ~10ms
- Storage: ~100ms
- **Total: ~600ms**
 
## 💡 Advanced Features (Optional)
 
```python
# Extract metadata
def extract_pdf_metadata(pdf_reader):
    return {
        "pages": len(pdf_reader.pages),
        "title": pdf_reader.metadata.title,
        "author": pdf_reader.metadata.author
    }
 
# Preserve page numbers
def chunk_with_page_info(pdf_reader, chunk_size=1000):
    for page_num, page in enumerate(pdf_reader.pages):
        text = page.extract_text()
        for chunk in chunk_text(text):
            yield {
                "text": chunk,
                "page": page_num + 1
            }
```
 
## 🚢 Deploy
 
```bash
git add .
git commit -m "Mini 5: PDF processing and chunking"
git push
```
 
## ❓ Troubleshooting
 
**PDF not extracting text?**
```bash
# Some PDFs are scanned images (need OCR)
# For now, stick with text-based PDFs
 
# Check extraction
uv run python -c "
from pypdf import PdfReader
pdf = PdfReader('sample.pdf')
print(pdf.pages[0].extract_text()[:100])
"
```
 
**Large PDFs slow?**
```python
# Process in chunks
CHUNK_SIZE = 1000
for i in range(0, len(text), CHUNK_SIZE):
    process_chunk(text[i:i+CHUNK_SIZE])
```
 
## 📚 Resources
 
- [pypdf Documentation](https://pypdf.readthedocs.io/)
- [PDF Text Extraction](https://github.com/py-pdf/pypdf)
- [Chunking Strategies](https://python.langchain.com/docs/modules/data_connection/document_loaders/)
 
## ⏱️ Timeline
 
- Setup: 20 min
- PDF extraction: 1 hour
- Chunking: 1 hour
- Testing: 45 min
- **Total: 3-4 hours**
 
## ✅ Checklist
 
- [ ] Install pypdf
- [ ] Create document models
- [ ] Implement PDF extraction
- [ ] Implement chunking
- [ ] Create upload endpoint
- [ ] Store chunks in DB
- [ ] Test with sample PDF
- [ ] Push to GitHub
 
## 🎯 Next: PROJECT 1
 
Ready to integrate everything? Go to `../../PROYECTOS_COMPLETOS/project-1-rag-assistant/`
 
---
 
**Made as part of Sr Backend Roadmap** 🚀
````
 
---
 
# MINI 6: Celery Basics
 
Nombre: `mini-6-celery-basics/README.md`
 
````markdown
# ⚙️ Mini 6: Celery Task Queue
 
Async task processing with Celery and Redis.
 
## 🎯 Learning Objectives
 
- ✅ Task queues concept
- ✅ Celery configuration
- ✅ Worker processes
- ✅ Task status tracking
- ✅ Message serialization
- ✅ Result storage
 
## 🏗️ Architecture
 
````
Request
    ↓
Enqueue task → Redis (broker)
    ↓
Worker picks up
    ↓
Executes task
    ↓
Store result → Redis (backend)
    ↓
Client checks status
````
 
## 📚 Tech Stack
 
- **FastAPI** - Web framework
- **Celery** 5.3+ - Task queue
- **Redis** 7+ - Message broker & result backend
- **Docker Compose** - Orchestration
 
## 🚀 Quick Start
 
```bash
# 1. Install
uv add celery redis
 
# 2. Start services
docker-compose up -d
 
# 3. Start worker
uv run celery -A app.celery_app worker --loglevel=info
 
# 4. Run app (different terminal)
uv run uvicorn app.main:app --reload
```
 
## 📝 API Endpoints
 
```bash
# Enqueue task
POST /tasks/enqueue
{
  "value": 42
}
 
Response:
{
  "task_id": "abc-123...",
  "status": "PENDING"
}
 
# Get task status
GET /tasks/{task_id}/status
 
Response:
{
  "task_id": "abc-123",
  "status": "STARTED"  # or SUCCESS, FAILED
}
 
# Get result (wait for completion)
GET /tasks/{task_id}/result
 
Response:
{
  "result": "Task completed: 42"
}
```
 
## 🔧 Celery Configuration
 
```python
from celery import Celery
 
app = Celery(
    "celery_app",
    broker="redis://localhost:6379",
    backend="redis://localhost:6379"
)
 
app.conf.update(
    task_serializer="json",
    result_serializer="json",
    timezone="UTC"
)
```
 
## 📋 Task Definition
 
```python
from app.celery_app import app
 
@app.task(bind=True)
def simple_task(self, value):
    print(f"Task ID: {self.request.id}")
    # Do work
    return f"Result: {value * 2}"
 
# Enqueue
task = simple_task.delay(42)
print(task.id)        # Get task ID
print(task.status)    # Get current status
print(task.result)    # Wait for result
```
 
## 📊 Task Lifecycle
 
````
1. PENDING  - Task waiting to be executed
2. STARTED  - Worker picked up task
3. SUCCESS  - Task completed successfully
4. FAILURE  - Task failed
5. RETRY    - Task retrying
````
 
## 📈 Celery Worker
 
```bash
# Start worker
celery -A app.celery_app worker --loglevel=info
 
# With concurrency (multiple processes)
celery -A app.celery_app worker -c 4 --loglevel=info
 
# Monitor tasks
celery -A app.celery_app inspect active
```
 
## 🎓 Key Concepts
 
**Broker vs Backend:**
- **Broker**: Queue (Redis) - receives tasks
- **Backend**: Storage (Redis) - stores results
 
**Task Serialization:**
- Convert Python objects → JSON
- Allows language interoperability
 
**Async Execution:**
```python
# Synchronous (blocks)
result = expensive_function()
print(result)
 
# Async with Celery
task = expensive_task.delay()
# Returns immediately
print("Task queued")
# Later...
print(task.result)  # Blocks until ready
```
 
## 🧪 Testing
 
```bash
# Send test task
curl -X POST http://localhost:8000/tasks/enqueue \
  -d '{"value": 100}'
 
# Check status
curl http://localhost:8000/tasks/{task_id}/status
 
# Wait for result
curl http://localhost:8000/tasks/{task_id}/result
```
 
## 📂 Folder Structure
 
````
mini-6-celery-basics/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── celery_app.py           # NEW: Celery config
│   ├── tasks.py                # NEW: Task definitions
│   └── routes/
│       └── tasks.py            # NEW: Task endpoints
├── docker-compose.yml          # Redis + app + worker
└── pyproject.toml
````
 
## 🔴 Redis as Queue
 
```bash
# Inspect queue
docker-compose exec redis redis-cli
 
# List tasks
LRANGE celery 0 -1
 
# Task count
LLEN celery
 
# Clear queue
DEL celery
```
 
## 📊 Production Patterns
 
```python
# Task with retry
@app.task(bind=True, max_retries=3)
def unreliable_task(self, data):
    try:
        return do_work(data)
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60)
 
# Periodic tasks (like cron)
from celery.schedules import crontab
 
app.conf.beat_schedule = {
    'every-30-seconds': {
        'task': 'app.tasks.my_periodic_task',
        'schedule': 30.0,
    },
}
```
 
## ⚡ Performance
 
- Task enqueueing: <1ms
- Task pickup: 100-500ms
- Execution: depends on task
- Result retrieval: <1ms
 
## 🚢 Deploy
 
```bash
# Include Celery worker in docker-compose
services:
  celery_worker:
    build: .
    command: celery -A app.celery_app worker
```
 
## ❓ Troubleshooting
 
**Workers not picking up tasks?**
```bash
# Check worker is running
celery -A app.celery_app inspect active
 
# Check broker connection
docker-compose logs redis
 
# Restart worker
docker-compose restart celery_worker
```
 
**Tasks stuck?**
```bash
# Clear queue
redis-cli FLUSHDB
 
# Restart
docker-compose restart
```
 
## 📚 Resources
 
- [Celery Documentation](https://docs.celeryproject.org/)
- [Celery Best Practices](https://celery.io/blog/best-practices/)
- [Task Queues](https://taskqueues.readthedocs.io/)
 
## ⏱️ Timeline
 
- Setup: 30 min
- Celery config: 30 min
- Task implementation: 1 hour
- Testing: 45 min
- **Total: 3-4 hours**
 
## ✅ Checklist
 
- [ ] Install Celery + Redis
- [ ] Configure Celery
- [ ] Define test tasks
- [ ] Create task endpoints
- [ ] Start worker separately
- [ ] Test task enqueuing
- [ ] Test status tracking
- [ ] Push to GitHub
 
## 🎯 Next: Mini 7
 
Ready for task monitoring? Go to `../mini-7-task-monitoring/`
 
---
 
**Made as part of Sr Backend Roadmap** 🚀
````
 
---
 
# MINI 7: Task Monitoring
 
Nombre: `mini-7-task-monitoring/README.md`
 
````markdown
# 📊 Mini 7: Task Retries & Monitoring
 
Advanced Celery: retries, monitoring, progress tracking.
 
## 🎯 Learning Objectives
 
- ✅ Retry logic (exponential backoff)
- ✅ Max retries configuration
- ✅ Task monitoring
- ✅ Progress tracking
- ✅ Worker statistics
- ✅ Dead letter queue concept
 
## 🏗️ Architecture
 
````
Task fails
    ↓
Retry with backoff (2^n seconds)
    ↓ (Max 3 retries)
If still failing
    ↓
Dead letter queue / alert
````
 
## 📚 Tech Stack
 
- **Celery** - Task queue (from Mini 6)
- **Redis** - Broker & backend
- **FastAPI** - Web framework
 
## 🚀 Quick Start
 
```bash
# Same setup as Mini 6
docker-compose up -d
 
# Start worker
uv run celery -A app.celery_app worker --loglevel=info
 
# Run app
uv run uvicorn app.main:app --reload
```
 
## 📋 Retry Logic
 
### Exponential Backoff
 
````
Retry 1: 2^0 = 1 second
Retry 2: 2^1 = 2 seconds
Retry 3: 2^2 = 4 seconds
→ Max retries reached → Failure
````
 
### Implementation
 
```python
@app.task(bind=True, max_retries=3)
def unreliable_task(self, data):
    try:
        return do_work(data)
    except Exception as exc:
        # Exponential backoff
        countdown = 2 ** self.request.retries
        raise self.retry(exc=exc, countdown=countdown)
```
 
## 📝 API Endpoints
 
```bash
# Test task with retries
POST /tasks/retry-test
{
  "data": "something"
}
 
# Get worker stats
GET /monitoring/workers
 
Response:
{
  "celery@worker1": {
    "pool": {"max-concurrency": 4},
    "total": 42,
    "tasks": {
      "task1": {...},
      "task2": {...}
    }
  }
}
 
# Get active tasks
GET /monitoring/active
 
Response:
{
  "celery@worker1": [
    {
      "id": "task-123",
      "name": "app.tasks.my_task",
      "args": [1, 2],
      "time_start": 1234567890
    }
  ]
}
```
 
## 🧪 Testing Retries
 
```bash
# Trigger task that will retry
curl -X POST http://localhost:8000/tasks/retry-test \
  -d '{"data": "fail"}'
 
# Watch worker logs
docker-compose logs celery_worker
 
# You should see:
# Retry 1: Task started
# (failure)
# Retrying in 1 second
# Retry 2: Task started
# (failure)
# Retrying in 2 seconds
# etc...
```
 
## 📊 Task Monitoring
 
### Celery Inspect
 
```python
from app.celery_app import app
 
inspect = app.control.inspect()
 
# Active tasks
active = inspect.active()
 
# Scheduled tasks
scheduled = inspect.scheduled()
 
# Worker stats
stats = inspect.stats()
```
 
### Progress Tracking
 
```python
@app.task(bind=True)
def long_task(self, n):
    for i in range(n):
        # Update progress
        self.update_state(
            state='PROGRESS',
            meta={'current': i, 'total': n}
        )
        time.sleep(1)
    return n
```
 
**Client side:**
```python
task = long_task.delay(100)
while True:
    result = app.AsyncResult(task.id)
    if result.state == 'PROGRESS':
        print(f"Progress: {result.info}")
    elif result.state == 'SUCCESS':
        break
```
 
## 🎓 Key Concepts
 
**Task States:**
- PENDING: Waiting
- STARTED: Running
- PROGRESS: Running with progress
- SUCCESS: Done
- FAILURE: Failed
- RETRY: Retrying
- REVOKED: Cancelled
 
**Dead Letter Queue:**
- Tasks that fail after all retries
- Need handling (alert, logging, etc)
 
## 📂 Folder Structure
 
````
mini-7-task-monitoring/
├── app/
│   ├── tasks.py              # UPDATED: Add retry logic
│   ├── services/
│   │   └── monitoring.py     # NEW: Monitoring logic
│   ├── routes/
│   │   ├── tasks.py          # UPDATED
│   │   └── monitoring.py     # NEW: Monitoring endpoints
│   └── celery_app.py         # (same)
├── docker-compose.yml        # (same)
└── pyproject.toml
````
 
## 📈 Monitoring Dashboard (Optional)
 
```python
# Add to routes
@app.get("/dashboard")
async def dashboard():
    inspect = app.control.inspect()
    return {
        "active_tasks": inspect.active(),
        "worker_stats": inspect.stats(),
        "scheduled": inspect.scheduled()
    }
```
 
## ⚡ Production Patterns
 
```python
# Task with error handling
@app.task(bind=True, max_retries=5)
def critical_task(self, data):
    try:
        return process_critical_data(data)
    except TemporaryError as exc:
        # Retry temporary failures
        raise self.retry(
            exc=exc,
            countdown=2 ** self.request.retries,
            max_retries=5
        )
    except PermanentError as exc:
        # Don't retry permanent failures
        logger.error(f"Permanent error: {exc}")
        raise
 
# Error alerts
@app.task
def send_error_alert(task_id, error):
    # Send to monitoring system
    alert_service.send(
        f"Task {task_id} failed: {error}"
    )
```
 
## 🚢 Deploy
 
```bash
# Include monitoring endpoints
# Keep worker separate for scaling
```
 
## ❓ Troubleshooting
 
**Tasks not retrying?**
```bash
# Check max_retries is set
# Check countdown value
# Look at worker logs
```
 
**Monitoring not showing tasks?**
```bash
# Make sure worker is running
docker-compose exec celery_worker celery -A app.celery_app inspect active
```
 
## 📚 Resources
 
- [Celery Retries](https://docs.celeryproject.org/en/stable/userguide/tasks.html#retrying)
- [Celery Monitoring](https://docs.celeryproject.org/en/stable/reference/celery.app.control.html)
- [Exponential Backoff](https://en.wikipedia.org/wiki/Exponential_backoff)
 
## ⏱️ Timeline
 
- Setup: 20 min (from Mini 6)
- Retry logic: 1 hour
- Monitoring: 1 hour
- Testing: 45 min
- **Total: 2-3 hours**
 
## ✅ Checklist
 
- [ ] Copy from Mini 6
- [ ] Implement retry logic
- [ ] Test retry mechanism
- [ ] Add monitoring service
- [ ] Create monitoring endpoints
- [ ] Test monitoring data
- [ ] Push to GitHub
 
## 🎯 Next: Mini 8
 
Ready for LLM tool calling? Go to `../mini-8-tool-calling/`
 
---
 
**Made as part of Sr Backend Roadmap** 🚀
````
 
---
 
# MINI 8: Tool Calling
 
Nombre: `mini-8-tool-calling/README.md`
 
````markdown
# 🔧 Mini 8: LLM Tool Calling
 
Enable LLMs to call functions via tool use.
 
## 🎯 Learning Objectives
 
- ✅ Tool definition and schema
- ✅ Tool calling pattern
- ✅ Function registry
- ✅ Tool execution
- ✅ Result feedback to LLM
- ✅ LLM reasoning loop basics
 
## 🏗️ Architecture
 
````
LLM Request
    ↓
LLM reasons + chooses tool
    ↓
Execute tool
    ↓
Send result back to LLM
    ↓
LLM generates response
````
 
## 📚 Tech Stack
 
- **FastAPI** - Web framework
- **Anthropic Claude** - LLM
- **Pydantic** - Schema validation
 
## 🚀 Quick Start
 
```bash
# 1. Install
uv add anthropic
 
# 2. Create .env
export ANTHROPIC_API_KEY=sk-ant-...
 
# 3. Run app
uv run uvicorn app.main:app --reload
```
 
## 📝 API Endpoints
 
```bash
# Simple tool calling
POST /agent/tool-calling
{
  "prompt": "What is 42 times 2?"
}
 
Response:
{
  "prompt": "What is 42 times 2?",
  "reasoning": "I need to calculate 42 * 2",
  "final_answer": "42 times 2 equals 84",
  "tools_used": ["calculate"]
}
```
 
## 🛠️ Defining Tools
 
### Tool Schema
 
```python
tool = {
  "name": "calculate",
  "description": "Calculate mathematical expression",
  "input_schema": {
    "type": "object",
    "properties": {
      "expression": {
        "type": "string",
        "description": "Math expression (e.g., '2 + 2')"
      }
    },
    "required": ["expression"]
  }
}
```
 
### Tool Implementation
 
```python
def calculate(expression: str) -> dict:
    """Execute math expression"""
    try:
        result = eval(expression)
        return {"result": result}
    except Exception as e:
        return {"error": str(e)}
```
 
### Tool Registry
 
```python
class ToolRegistry:
    def __init__(self):
        self.tools = {}
    
    def register(self, name, desc, schema, func):
        self.tools[name] = {
            "name": name,
            "description": desc,
            "input_schema": schema,
            "func": func
        }
    
    def execute(self, name, input_dict):
        tool = self.tools[name]
        return tool["func"](**input_dict)
```
 
## 🧠 LLM Tool Calling Flow
 
```python
from anthropic import Anthropic
 
client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
 
# 1. Send prompt + tools to Claude
response = client.messages.create(
    model="claude-3-5-sonnet-20241022",
    max_tokens=1024,
    tools=registry.get_tools_for_api(),
    messages=[{
        "role": "user",
        "content": "Calculate 42 * 2"
    }]
)
 
# 2. Check if Claude wants to use tool
for block in response.content:
    if block.type == "tool_use":
        # Execute tool
        result = registry.execute(block.name, block.input)
        
        # Send result back
        messages.append({
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": str(result)
            }]
        })
```
 
## 📊 Tool Calling vs Function Calling
 
**Tool Calling (Claude):**
```python
tools=[{...}]
# Claude returns: tool_use block
```
 
**Function Calling (OpenAI):**
```python
functions=[{...}]
# GPT returns: function_call object
```
 
Same concept, different API.
 
## 🧪 Testing
 
```bash
# Simple calculation
curl -X POST http://localhost:8000/agent/tool-calling \
  -d '{"prompt": "Calculate 10 + 5"}'
 
# Multiple tool query
curl -X POST http://localhost:8000/agent/tool-calling \
  -d '{"prompt": "What time is it? Also, calculate 100 * 2"}'
 
# Expected: tools_used: ["get_time", "calculate"]
```
 
## 🎓 Available Tools (Mini 8)
 
```python
# 1. Search
def search(query: str) -> dict
 
# 2. Calculate
def calculate(expression: str) -> dict
 
# 3. Get time
def get_current_time() -> dict
```
 
## 📂 Folder Structure
 
````
mini-8-tool-calling/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── tools.py                # NEW: Tool definitions
│   ├── schemas/
│   │   └── agent.py           # NEW: Request/response
│   └── routes/
│       └── agent.py           # NEW: Agent endpoints
└── pyproject.toml
````
 
## ⚡ Key Concepts
 
**Tool Use Block:**
```python
{
  "type": "tool_use",
  "id": "tool_use_123",
  "name": "calculate",
  "input": {"expression": "42 * 2"}
}
```
 
**Tool Result Block:**
```python
{
  "type": "tool_result",
  "tool_use_id": "tool_use_123",
  "content": "84"
}
```
 
## 🚢 Deploy
 
```bash
git add .
git commit -m "Mini 8: LLM tool calling"
git push
```
 
## ❓ Troubleshooting
 
**Tool not being called?**
```bash
# Check tool is in registry
# Check tool description is clear
# Check input schema is correct
```
 
**Tool result not used?**
```bash
# Make sure tool_result block is correct
# Check tool_use_id matches
# Print full response for debugging
```
 
## 📚 Resources
 
- [Claude Tool Use](https://docs.anthropic.com/claude/docs/tool-use)
- [Tool Definition](https://docs.anthropic.com/claude/reference/tool-use)
- [Function Calling Patterns](https://platform.openai.com/docs/guides/function-calling)
 
## ⏱️ Timeline
 
- Setup: 20 min
- Tool registry: 1 hour
- Tool calling: 1.5 hours
- Testing: 30 min
- **Total: 3-4 hours**
 
## ✅ Checklist
 
- [ ] Install Anthropic SDK
- [ ] Define tool schemas
- [ ] Implement tool functions
- [ ] Create tool registry
- [ ] Implement tool calling
- [ ] Test basic queries
- [ ] Test multiple tools
- [ ] Push to GitHub
 
## 🎯 Next: Mini 9
 
Ready for full agent loop? Go to `../mini-9-agent-loop/`
 
---
 
**Made as part of Sr Backend Roadmap** 🚀
````
 
---
 
# MINI 9: Agent Loop
 
Nombre: `mini-9-agent-loop/README.md`
 
````markdown
# 🔁 Mini 9: Agent Reasoning Loop
 
Full agent loop with multi-step reasoning.
 
## 🎯 Learning Objectives
 
- ✅ Agent loop pattern
- ✅ Stop conditions
- ✅ Multi-step reasoning
- ✅ Tool chaining
- ✅ Max iterations safety
- ✅ Error recovery
 
## 🏗️ Architecture
 
````
While not done:
  1. Send prompt + tools to LLM
  2. LLM thinks and chooses tool(s)
  3. Execute tool(s)
  4. Feed result back to LLM
  5. Check stop condition
````
 
## 📚 Tech Stack
 
- **FastAPI** - Web framework
- **Anthropic Claude** - LLM
- **Tool registry** - From Mini 8
 
## 🚀 Quick Start
 
```bash
# Copy from Mini 8 + add agent executor
uv run uvicorn app.main:app --reload
```
 
## 📝 API Endpoints
 
```bash
# Multi-step agent task
POST /agent/execute-loop
{
  "prompt": "Calculate 50 + 30, then multiply by 2. Also tell me the time."
}
 
Response:
{
  "final_answer": "50 + 30 = 80, multiplied by 2 = 160. Current time is...",
  "iterations": 2,
  "tools_used": ["calculate", "get_time"],
  "execution_log": [...]
}
```
 
## 🧠 Agent Loop Implementation
 
```python
async def execute(self, prompt: str) -> dict:
    messages = [{"role": "user", "content": prompt}]
    iteration = 0
    
    while iteration < self.max_iterations:
        iteration += 1
        
        # 1. Call LLM
        response = self.client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1024,
            tools=registry.get_tools_for_api(),
            messages=messages
        )
        
        # 2. Check stop condition
        if response.stop_reason == "end_turn":
            # LLM decided it's done
            return extract_text_response(response)
        
        # 3. Process tool calls
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                result = registry.execute(block.name, block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": str(result)
                })
        
        # 4. Feed back to LLM
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})
    
    # Max iterations reached
    return {"error": "Max iterations exceeded"}
```
 
## 📊 Execution Flow Example
 
````
User: "Find flights BA→Barcelona under $800, and notify me"
 
Iteration 1:
  LLM: "I need to search for flights"
  Call: search_flights("BA", "Barcelona", 800)
  Result: [Flights found: LATAM $750]
  
Iteration 2:
  LLM: "Found flights under budget. Send notification."
  Call: send_notification("user123", "Found LATAM $750")
  Result: Notification sent
  
Iteration 3:
  LLM: "Task complete"
  Stop: end_turn
  
Final: "I found a LATAM flight for $750 and sent notification"
````
 
## 🎓 Key Concepts
 
**Stop Reason:**
- "end_turn": LLM finished reasoning
- "tool_use": LLM wants to use tool(s)
- "max_tokens": Hit token limit
 
**Max Iterations:**
- Safety mechanism
- Prevent infinite loops
- Default: 10 iterations
 
**Execution Log:**
```python
{
  "iteration": 1,
  "stop_reason": "tool_use",
  "tools_called": ["search_flights"],
  "text": "I'll search for flights..."
}
```
 
## 🧪 Testing Complex Scenarios
 
```bash
# Simple task (1 iteration)
curl -X POST http://localhost:8000/agent/execute-loop \
  -d '{"prompt": "What time is it?"}'
 
# Medium task (2 iterations)
curl -X POST http://localhost:8000/agent/execute-loop \
  -d '{"prompt": "Calculate 50 + 30, then tell me the time"}'
 
# Complex task (3+ iterations)
curl -X POST http://localhost:8000/agent/execute-loop \
  -d '{"prompt": "Search for Python, calculate 10 * 5, get time, then summarize"}'
```
 
## 📂 Folder Structure
 
````
mini-9-agent-loop/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── tools.py                 # From Mini 8
│   ├── services/
│   │   └── agent_executor.py   # NEW: Agent loop
│   ├── schemas/
│   │   └── agent.py
│   └── routes/
│       └── agent.py             # UPDATED: Add loop endpoint
└── pyproject.toml
````
 
## 📈 Performance
 
**Expected:**
- Iteration 1: ~500-1000ms (LLM call + tool)
- Iteration 2: ~500-1000ms
- Total for 2-3 tools: ~1-3 seconds
 
## ⚡ Advanced Patterns
 
**With Database Persistence:**
```python
# Save execution log
task = Task(
    id=task_id,
    prompt=prompt,
    status="running",
    execution_log=[]
)
db.add(task)
 
# Update after each iteration
task.execution_log.append(iteration_log)
db.commit()
```
 
**With Error Recovery:**
```python
try:
    result = registry.execute(tool_name, tool_input)
except Exception as e:
    # Don't break loop, inform LLM
    tool_results.append({
        "type": "tool_result",
        "tool_use_id": block.id,
        "content": f"Error: {e}",
        "is_error": True
    })
    # LLM will try different approach
```
 
## 🚢 Deploy
 
```bash
git add .
git commit -m "Mini 9: Agent reasoning loop"
git push
```
 
## ❓ Troubleshooting
 
**Agent stuck in loop?**
```bash
# Check max_iterations
# Check stop_reason is "end_turn"
# Check tool execution time
 
# Increase timeout if needed
task_time_limit = 60  # seconds
```
 
**Tool not executing next iteration?**
```bash
# Check tool_use_id is correct
# Check tool_result structure
# Look at message history
 
# Debug:
print(f"Messages: {messages}")
print(f"Response: {response}")
```
 
## 📚 Resources
 
- [ReAct Pattern](https://arxiv.org/abs/2210.03629)
- [Agent Frameworks](https://python.langchain.com/docs/modules/agents/)
- [Anthropic Tool Use](https://docs.anthropic.com/claude/docs/tool-use)
 
## ⏱️ Timeline
 
- Setup: 20 min (from Mini 8)
- Agent loop: 1.5 hours
- Testing: 1 hour
- **Total: 3-4 hours**
 
## ✅ Checklist
 
- [ ] Copy from Mini 8
- [ ] Implement agent executor
- [ ] Handle multi-iteration
- [ ] Implement stop conditions
- [ ] Add max iterations safety
- [ ] Test simple queries
- [ ] Test complex workflows
- [ ] Push to GitHub
 
## 🎯 Next: PROJECT 2
 
Ready to combine Celery + Agents? Go to `../../PROYECTOS_COMPLETOS/project-2-agentic-backend/`
 
---
 
**Made as part of Sr Backend Roadmap** 🚀
````
 
---
 
# 📋 Cómo Usar
 
Para cada mini proyecto:
 
1. **Crea carpeta:**
````bash
   mkdir mini-X-nombre
   cd mini-X-nombre
````
 
2. **Copia el README correspondiente:**
````bash
   # Copia el contenido de arriba
   # Pégalo en mini-X-nombre/README.md
````
 
3. **Sigue las instrucciones:**
   - Lee el README
   - Sigue Quick Start
   - Copia templates
   - Codea
¡Listo! Cada mini tiene su propio README profesional 🚀
 