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
