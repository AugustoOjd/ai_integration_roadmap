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
