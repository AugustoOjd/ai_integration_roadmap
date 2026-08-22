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
docker compose up -d postgres
 
# 2. Install dependencies
uv sync
 
# 3. Run app
uv run uvicorn app.main:app --reload
```
 
Or run the whole stack in containers:
 
```bash
docker compose up --build
```
 
### Load data and measure
 
```bash
# 10,000 synthetic notes across 5 topics (a few minutes: it embeds all of them)
uv run python -m scripts.seed 10000
 
# No index vs IVFFlat vs HNSW — latency AND recall
uv run python -m scripts.benchmark
```
 
`-m` (not `python scripts/seed.py`) puts the cwd on `sys.path` so `import app` resolves.
 
### Tests
 
```bash
uv run pytest -v
```
 
They create and drop a separate `mini_db_test` database, so the seeded data is left alone.
 
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
  embedding vector(384),  -- NEW: Vector column — 384 = all-MiniLM-L6-v2 (Mini 3).
                          -- The size is fixed at CREATE TABLE time: changing the
                          -- embedding model means ALTER TABLE + regenerating every row.
  created_at TIMESTAMP
);
```
 
The index is **not** created here — see below.
 
> ⚠️ **Never build an IVFFlat index on an empty table.**
> IVFFlat learns its cluster centroids from the rows present at build time, and a
> query only scans `ivfflat.probes` clusters (**1** by default). Built empty, the
> centroids are meaningless: the one cluster the query opens is likely empty and
> the search returns **zero rows** — no error, no warning.
> This is exactly what happens if you put the index in `__table_args__`, because
> `create_all()` runs before any data exists. So the model declares only the
> column, and `scripts/benchmark.py` creates the index after loading data — which
> is also what you do in production.
 
```sql
-- Run this AFTER the table has data. lists ≈ rows/1000 (up to 1M rows).
-- vector_cosine_ops means only the <=> operator can use this index.
CREATE INDEX ix_notes_embedding
  ON notes USING ivfflat (embedding vector_cosine_ops) WITH (lists = 10);
```
 
## 📊 pgvector Operators
 
```sql
-- Cosine distance (what we use — pairs with vector_cosine_ops)
SELECT * FROM notes
ORDER BY embedding <=> query_embedding
LIMIT 5;
 
-- L2 / Euclidean distance (pairs with vector_l2_ops)
ORDER BY embedding <-> query_embedding
 
-- Negative inner product (pairs with vector_ip_ops)
ORDER BY embedding <#> query_embedding
```
 
## 🎓 Key Concepts
 
**Vector Operators:**
```python
# In SQL — each operator has a matching index operator class:
# <=>  = cosine distance          → vector_cosine_ops   (preferred for embeddings)
# <->  = L2 / Euclidean distance  → vector_l2_ops
# <#>  = NEGATIVE inner product   → vector_ip_ops       (multiply by -1 for the real value)
```
 
> ⚠️ **The operator must match the index's operator class or the index is ignored.**
> An index built with `vector_cosine_ops` is only used by `<=>`. Query it with
> `<->` and Postgres silently falls back to a full table scan *and* ranks by the
> wrong metric — no error, just slow and subtly wrong results. Confirm with
> `EXPLAIN ANALYZE`: an `Index Scan` means it's working, a `Seq Scan` means it isn't.
 
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
 
The SQL we want Postgres to run:
 
```sql
SELECT id, title, content, 1 - (embedding <=> $1) AS similarity
FROM notes
WHERE embedding IS NOT NULL
ORDER BY embedding <=> $1
LIMIT $2
```
 
Built through the ORM rather than `text()`, so pgvector serializes the list into
a `vector` bind param instead of us formatting a string by hand:
 
```python
# cosine_distance() comes from Vector's comparator_factory and emits `<=>`.
# Your IDE won't autocomplete it — it's resolved at runtime, not statically.
distance = Note.embedding.cosine_distance(query_embedding)
 
stmt = (
    select(Note, (1 - distance).label("similarity"))
    .where(Note.embedding.is_not(None))
    .order_by(distance)          # raw distance, NOT `similarity` — see below
    .limit(top_k)
)
result = await db.execute(stmt)
```
 
Three things that are easy to get wrong:
 
- **Reuse the `distance` object.** Referencing it in both `SELECT` and `ORDER BY`
  makes both compile to the same bind param, so the 384-float vector crosses the
  wire once instead of twice.
- **Order by the raw distance, not by `similarity`.** `1 - (a <=> b)` is a derived
  expression the index cannot match; ordering by it forces a Seq Scan.
- **`LIMIT` is not just output trimming.** It is what lets the index stop after a
  few clusters instead of ranking the whole table.
 
## 📂 Folder Structure
 
````
mini-4-pgvector/
├── app/
│   ├── main.py                  # lifespan: loads model, checks dim, init_db
│   ├── config.py                # settings + EMBEDDING_DIM + NORMALIZE_EMBEDDINGS
│   ├── database.py              # UPDATED: CREATE EXTENSION before create_all
│   ├── models/
│   │   └── note.py              # UPDATED: embedding column (no index — see above)
│   ├── services/
│   │   ├── embeddings.py        # From Mini 3, single model + embed_many()
│   │   └── search.py            # NEW: the <=> query
│   ├── routes/
│   │   └── notes.py             # NEW: POST /notes/ and POST /notes/search
│   └── schemas/
│       └── note.py              # NEW: SearchRequest / SearchResult
├── scripts/
│   ├── seed.py                  # NEW: N synthetic notes across 5 topics
│   └── benchmark.py             # NEW: no index vs IVFFlat vs HNSW
├── tests/
│   ├── conftest.py              # separate mini_db_test, rollback per test
│   └── test_search.py
├── init.sql                     # CREATE EXTENSION on first boot
├── docker-compose.yml           # UPDATED: pgvector image + app service
└── pyproject.toml               # UPDATED: Add pgvector
````
 
## 🔧 Setup pgvector
 
```bash
# docker-compose.yml uses pgvector image
image: pgvector/pgvector:pg16
 
# Enable in code — text() is required, SQLAlchemy 2.0 rejects raw strings.
# Order matters: create_all emits `embedding vector(384)` and Postgres
# rejects an unknown type.
async def init_db():
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
```
 
This duplicates `init.sql` on purpose: that file only runs on a fresh Docker
volume, and does not exist at all on managed Postgres (RDS, Supabase, Neon).
 
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
ORDER BY embedding <=> query_embedding
LIMIT 10;
```
 
3. **Batch searches:**
- Process multiple queries together
- Reuse connection pool
 
## 📊 Benchmark
 
Measured with `scripts/benchmark.py` — 10,000 notes, 384-D, top_k=10,
5 queries × 20 repetitions, laptop CPU:
 
| Config | Median | p95 | Recall | Build |
|---|---|---|---|---|
| No index (Seq Scan) | 5.3 ms | 6.5 ms | 100% | — |
| IVFFlat (`lists=10`) | 1.1 ms | 1.4 ms | **96%** | 0.1 s |
| HNSW | 0.8 ms | 1.1 ms | 100% | 0.7 s |
 
**Two things worth noticing, because they contradict the usual pitch:**
 
1. **The speedup is ~5x, not 50x.** 10,000 dot products over 384 dimensions is
   trivial work for a modern CPU, and pgvector uses SIMD. At this scale the index
   is a nicety. It becomes essential at hundreds of thousands of rows — try
   `uv run python -m scripts.seed 200000` to watch the Seq Scan degrade while the
   index times barely move.
 
2. **Recall is the axis that actually matters.** IVFFlat missing 4% of the true
   top-10 is the price of its speed, and latency alone would never show it. An
   index that is 50x faster but loses 40% of results is worthless — always measure
   both. The benchmark gets its ground truth by forcing `enable_indexscan = off`.
 
HNSW being both faster *and* more accurate is the expected trade: it pays for it
at build time (7x slower here, and the gap widens with scale).
 
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
 
- [x] Use pgvector Docker image
- [x] Create vector column in notes
- [x] Implement embedding generation
- [x] Add search endpoint
- [x] Create similarity index — **after** loading data, not in `create_all`
- [x] Test search results
- [x] Benchmark performance — latency *and* recall
- [ ] Push to GitHub
 
## 🎯 Next: Mini 5
 
Ready for PDF processing? Go to `../mini-5-pdf-processing/`
 
---
 
**Made as part of Sr Backend Roadmap** 🚀
