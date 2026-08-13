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
