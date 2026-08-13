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
