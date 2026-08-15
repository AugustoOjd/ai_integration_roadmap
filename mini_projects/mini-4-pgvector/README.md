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
  embedding vector(384),  -- NEW: Vector column — 384 = all-MiniLM-L6-v2 (Mini 3).
                          -- The size is fixed at CREATE TABLE time: changing the
                          -- embedding model means ALTER TABLE + regenerating every row.
  created_at TIMESTAMP
);
 
-- INDEX for faster search.
-- vector_cosine_ops means only the <=> operator can use this index.
CREATE INDEX ix_notes_embedding 
  ON notes USING ivfflat(embedding vector_cosine_ops);
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
 
```python
# Search implementation
search_query = """
SELECT 
  id,
  title,
  content,
  (1 - (embedding <=> :embedding)) as similarity
FROM notes
WHERE embedding IS NOT NULL
ORDER BY embedding <=> :embedding
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
ORDER BY embedding <=> query_embedding
LIMIT 10;
```
 
3. **Batch searches:**
- Process multiple queries together
- Reuse connection pool
 
## 📊 Benchmark
 
````
Setup: 10,000 notes, 384-D embeddings
 
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
