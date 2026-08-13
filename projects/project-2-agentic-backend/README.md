# 🤖 PROJECT 2: Agentic Backend

**Complete integration of Mini Projects 6-9**

Build a production-ready agent system that executes complex workflows using LLM reasoning.

## 📌 When to Start This Project

**Prerequisites:** Complete Mini 6-9 first

```
Mini 6 → Mini 7 → Mini 8 → Mini 9 ✅
                              ↓
                         PROJECT 2 ← You are here
```

**Timeline:** Week 8-9 (after ~20 hours of mini projects + 10-15 hours of Project 1)

## 🎯 What You'll Build

A complete agent system that:
1. Accepts task descriptions from users
2. Uses LLM reasoning to break down tasks
3. Calls multiple tools in sequence
4. Tracks execution with retry logic
5. Stores results in database
6. Provides monitoring and status tracking

**Real-world use case:** Workflow automation, task automation, intelligent assistants

## 🏗️ Architecture

```
┌──────────────────────────────────────────────────┐
│            FastAPI Application                    │
├──────────────────────────────────────────────────┤
│                                                  │
│  POST /tasks/create                              │
│    ├─ Accept task description                    │
│    ├─ Create task record in DB                   │
│    └─ Enqueue in Celery (Redis)                  │
│                                                  │
│  GET /tasks/{task_id}                            │
│    └─ Check task status & result                 │
│                                                  │
│  GET /monitoring/...                             │
│    ├─ Active tasks                               │
│    └─ Worker statistics                          │
│                                                  │
└──────────────────────────────────────────────────┘
         ↓              ↓              ↓
    PostgreSQL       Redis         Celery Worker
    (task storage)   (queue)       (executes tasks)
                       ↓
                  Anthropic Claude
                  (agent reasoning)
```

## 📋 Agent Execution Flow

```
User creates task:
"Find flights BA→Barcelona under $800, notify me"
         ↓
Task enqueued in Redis
         ↓
Celery worker picks up
         ↓
Agent Iteration 1:
  - LLM reasons: "Need to search flights"
  - Calls: search_flights("BA", "Barcelona", 800)
  - Result: LATAM $750
         ↓
Agent Iteration 2:
  - LLM reasons: "Found flights, send notification"
  - Calls: send_notification("user123", "Found $750 flight")
  - Result: Notification sent
         ↓
Agent Final:
  - Stop reason: "end_turn"
  - Final answer: "Task completed successfully"
         ↓
Task marked SUCCESS in database
         ↓
User polls /tasks/{task_id}
  → Gets result + execution log
```

## 📚 Tech Stack

### Core
- **FastAPI** 0.109+ - Web framework
- **Python** 3.11+ - Runtime

### Task Queue & Async
- **Celery** 5.3+ - Distributed task queue
- **Redis** 7+ - Message broker & result backend

### Database
- **PostgreSQL** 16 - Task storage
- **SQLAlchemy** 2.0+ - Async ORM

### AI/LLM
- **Anthropic Claude** - Agent reasoning
- **LangChain** (optional) - Utilities
- **Tool registry** - Custom tools

### Infrastructure
- **Docker** - Containerization
- **Docker Compose** - Local orchestration
- **Terraform** - Infrastructure as Code
- **GitHub Actions** - CI/CD

### Deployment
- **Railway** or **AWS** - Production hosting

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
# 1. Navigate to project
cd project-2-agentic-backend

# 2. Install dependencies
poetry install

# 3. Setup environment
cp .env.example .env
# Edit .env with your ANTHROPIC_API_KEY

# 4. Start services
docker-compose up -d

# 5. Verify postgres is ready
docker-compose logs postgres | grep "ready"

# 6. In SEPARATE TERMINAL: Start Celery worker
poetry run celery -A app.celery_app worker --loglevel=info

# 7. In ANOTHER TERMINAL: Run app
poetry run uvicorn app.main:app --reload

# 8. Test
curl http://localhost:8000/health
curl http://localhost:8000/docs
```

## 📝 API Endpoints

### Task Management

```bash
# Create task (async)
POST /tasks/create
{
  "title": "Find Flights",
  "description": "Find flights from BA to Barcelona under $800 and notify me"
}

Response:
{
  "id": "task-123",
  "title": "Find Flights",
  "status": "pending",
  "created_at": "2024-01-15T10:00:00Z"
}

# Get task status
GET /tasks/task-123

Response:
{
  "id": "task-123",
  "status": "running",  # or success, failed
  "result": null,       # null while running
  "execution_log": [],
  "error": null,
  "started_at": "2024-01-15T10:00:10Z"
}

# When complete:
{
  "id": "task-123",
  "status": "success",
  "result": {
    "final_answer": "Found LATAM flight for $750. Notification sent.",
    "iterations": 2,
    "tools_used": ["search_flights", "send_notification"]
  },
  "execution_log": [...],
  "completed_at": "2024-01-15T10:00:35Z"
}

# List tasks (with optional filter)
GET /tasks/?status=running
GET /tasks/?status=success

# Get all
GET /tasks/
```

### Monitoring

```bash
# Worker statistics
GET /monitoring/workers

Response:
{
  "celery@worker1": {
    "pool": {"max-concurrency": 4},
    "total": 42,
    "rusage": {...}
  }
}

# Active tasks
GET /monitoring/active

Response:
{
  "celery@worker1": [
    {
      "id": "task-123",
      "name": "app.tasks.execute_agent_task",
      "time_start": 1234567890
    }
  ]
}

# Scheduled tasks
GET /monitoring/scheduled
```

## 📂 Folder Structure

```
project-2-agentic-backend/
│
├── README.md                    (this file)
├── pyproject.toml              (Poetry dependencies)
├── docker-compose.yml          (All services)
├── Dockerfile                  (Container image)
├── .env.example                (Config template)
├── .dockerignore
├── .gitignore
│
├── .github/
│   └── workflows/
│       └── deploy.yml          (CI/CD pipeline)
│
├── infra/                      (Infrastructure as Code)
│   ├── main.tf
│   ├── variables.tf
│   └── outputs.tf
│
├── app/
│   ├── __init__.py
│   ├── main.py                 (FastAPI app)
│   ├── config.py               (Settings)
│   ├── database.py             (DB connection)
│   ├── celery_app.py           (Celery config)
│   │
│   ├── models/                 (SQLAlchemy models)
│   │   ├── __init__.py
│   │   └── task.py             (Task table)
│   │
│   ├── schemas/                (Pydantic schemas)
│   │   ├── __init__.py
│   │   └── task.py
│   │
│   ├── services/               (Business logic)
│   │   ├── __init__.py
│   │   ├── agent_executor.py   (Agent loop)
│   │   ├── agent_tools.py      (Tool definitions)
│   │   └── monitoring.py       (Worker monitoring)
│   │
│   ├── tasks/                  (Celery tasks)
│   │   ├── __init__.py
│   │   └── agent_tasks.py      (Async execution)
│   │
│   ├── routes/                 (API endpoints)
│   │   ├── __init__.py
│   │   └── tasks.py            (Task management)
│   │
│   └── utils/                  (Utilities)
│       ├── __init__.py
│       └── logging.py
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_tasks.py
│   ├── test_agent.py
│   └── test_tools.py
│
├── docs/
│   ├── architecture.md         (System design)
│   ├── api.md                  (API reference)
│   ├── agent_workflow.md       (How agents work)
│   └── deployment.md           (Deploy guides)
│
└── samples/
    └── agent_examples.txt      (Example tasks)
```

## 🎓 Learning Path

### Integrating Mini Projects

| Mini | Integration in PROJECT 2 |
|------|--------------------------|
| Mini 6 | Celery task enqueueing |
| Mini 7 | Task retries + monitoring |
| Mini 8 | Tool definitions & calling |
| Mini 9 | Agent reasoning loop |

### New Concepts

- **Production task queues:** Scaling workers
- **Database persistence:** Task history & audit logs
- **Error recovery:** Retries, dead letters, circuit breakers
- **Real-time updates:** Task status polling/websockets
- **Monitoring:** Worker health, active tasks

## 🛠️ Agent Tools (Examples)

### Available Tools

```python
# 1. Search
search_flights(origin, destination, max_price)
  → Returns list of flights

# 2. Notification
send_notification(user_id, message, channel)
  → Sends email/SMS/push

# 3. Calculate
calculate_price_difference(base_price, current_price)
  → Returns diff and percentage

# 4. Database operations
create_booking(user_id, flight_info)
  → Books flight in DB
```

### Extending Tools

```python
# In app/services/agent_tools.py

def my_custom_tool(param1: str, param2: int) -> dict:
    """Do something useful"""
    result = ...
    return {"status": "success", "data": result}

# Register
registry.register(
    name="my_tool",
    description="Description of what tool does",
    schema={
        "type": "object",
        "properties": {
            "param1": {"type": "string"},
            "param2": {"type": "integer"}
        },
        "required": ["param1", "param2"]
    },
    func=my_custom_tool
)
```

## 🧪 Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=app

# Test agent execution
pytest tests/test_agent.py -v -s

# Test tool calling
pytest tests/test_tools.py

# Integration test (full flow)
pytest tests/test_tasks.py::test_full_agent_workflow -v
```

## 📊 Performance Characteristics

### Task Execution Timeline

```
Time 0:    POST /tasks/create
             └─ Response: {"id": "task-123", "status": "pending"}

Time 10ms: Task enqueued in Redis

Time 100ms: Celery worker picks up

Time 500ms: Agent Iteration 1
             - LLM call: ~500ms
             - Tool execution: ~100ms

Time 1000ms: Agent Iteration 2
              - LLM call: ~500ms
              - Tool execution: ~50ms

Time 1200ms: Agent completes
              - Task marked SUCCESS
              - Result saved in DB

Total: ~1.2 seconds end-to-end
```

### Throughput

**With 1 Worker:**
- Tasks/second: ~10-15
- Avg latency: 1-2 seconds

**With 4 Workers:**
- Tasks/second: ~40-60
- Avg latency: 1-2 seconds (unchanged)

### Concurrency

```python
# Start multiple workers for scaling
celery -A app.celery_app worker -c 4  # 4 concurrent tasks
celery -A app.celery_app worker -c 8  # 8 concurrent tasks

# Monitor
celery -A app.celery_app inspect active_queues
```

## 🎯 Retry & Error Handling

### Retry Logic

```python
@app.task(bind=True, max_retries=3)
def execute_agent_task(self, task_id: str):
    try:
        # Execute agent
        result = executor.execute(task.description)
        # Save result
        task.status = "success"
        db.commit()
    except TemporaryError as exc:
        # Retry with exponential backoff
        # Retry 1: 1 second
        # Retry 2: 2 seconds
        # Retry 3: 4 seconds
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)
    except PermanentError as exc:
        # Don't retry
        task.status = "failed"
        task.error = str(exc)
        db.commit()
        raise
```

### Dead Letter Queue

Tasks that fail after all retries are:
1. Marked as FAILED in database
2. Logged for analysis
3. Can trigger alerts/notifications

## 🚢 Deployment

### Option 1: Railway

```bash
# 1. Push to GitHub
git add .
git commit -m "Project 2: Agentic backend"
git push

# 2. Connect Railway
# - Create new project
# - Connect GitHub
# - Add PostgreSQL plugin
# - Add Redis plugin

# 3. Set environment
ANTHROPIC_API_KEY=sk-ant-...
CELERY_BROKER_URL=redis://...
CELERY_RESULT_BACKEND=redis://...

# 4. Deploy!
# Railway detects docker-compose
```

### Option 2: AWS with Terraform

```bash
# 1. Configure Terraform
cd infra
terraform init
terraform plan
terraform apply

# 2. Push Docker image
# (same as Project 1)

# 3. Deploy
# GitHub Actions auto-deploys

# 4. Scale workers (add more containers)
aws ecs update-service \
  --cluster rag-cluster \
  --service agent-workers \
  --desired-count 4
```

## 📊 Monitoring & Alerts

### Health Endpoint

```bash
GET /health

Response:
{
  "status": "ok",
  "database": "connected",
  "redis": "connected",
  "celery_workers": 4,
  "active_tasks": 12
}
```

### Metrics to Track

```
✅ Tasks enqueued per minute
✅ Average task duration
✅ Task failure rate
✅ Retry rate
✅ Worker health
✅ Redis queue length
✅ Database connection pool usage
✅ LLM API latency
```

### Alerts to Setup

```
🔔 Task failure rate > 5%
🔔 Worker disconnected
🔔 Queue length > 1000
🔔 Task timeout
🔔 Redis memory > 80%
```

## 📂 Task Lifecycle

```
CREATE (pending)
   ↓
RUNNING (agent executing)
   ├─ Iteration 1
   ├─ Iteration 2
   └─ Iteration N
   ↓
SUCCESS (saved result)
   OR
FAILED (error, max retries exceeded)
   OR
RETRY (temporary failure, waiting)
```

## 🎓 Key Concepts

### Agent Loop Pattern

```python
iteration = 0
messages = [{"role": "user", "content": prompt}]

while iteration < MAX_ITERATIONS:
    # 1. LLM reasons
    response = llm.call(tools=tools, messages=messages)
    
    # 2. Check stop
    if response.stop_reason == "end_turn":
        return extract_answer(response)
    
    # 3. Execute tools
    tool_results = execute_tools(response.tool_calls)
    
    # 4. Feedback
    messages.append({"role": "assistant", ...})
    messages.append({"role": "user", "content": tool_results})
    
    iteration += 1
```

### Celery Task States

- **PENDING:** Waiting in queue
- **STARTED:** Worker picked up
- **PROGRESS:** Running (optional)
- **SUCCESS:** Completed
- **FAILURE:** Error (no retry)
- **RETRY:** Retrying after failure
- **REVOKED:** Cancelled

## ❓ Troubleshooting

### Workers Not Processing Tasks

```bash
# Check worker is running
celery -A app.celery_app inspect active

# Check queue has tasks
redis-cli LLEN celery

# View worker logs
docker-compose logs celery_worker

# Restart worker
docker-compose restart celery_worker
```

### Tasks Stuck

```bash
# Clear queue
redis-cli FLUSHDB

# Or purge specific queue
redis-cli DEL celery

# Restart everything
docker-compose down
docker-compose up -d
```

### Agent Not Using Tools

```bash
# Check tools are registered
curl http://localhost:8000/docs
# Look at agent endpoint

# Test tool calling directly
curl -X POST http://localhost:8000/agent/tool-calling \
  -d '{"prompt": "Use a tool"}'

# Check worker logs for errors
docker-compose logs celery_worker | grep "error\|ERROR"
```

## 📖 Documentation

- **[architecture.md](./docs/architecture.md)** - System design
- **[api.md](./docs/api.md)** - API reference
- **[agent_workflow.md](./docs/agent_workflow.md)** - Agent details
- **[deployment.md](./docs/deployment.md)** - Deployment guide

## 🔗 Resources

- [Celery Documentation](https://docs.celeryproject.org/)
- [ReAct Paper](https://arxiv.org/abs/2210.03629) (Agent pattern)
- [LangChain Agents](https://python.langchain.com/docs/modules/agents/)
- [Anthropic Tool Use](https://docs.anthropic.com/claude/docs/tool-use)

## ⏱️ Timeline

| Phase | Time | Tasks |
|-------|------|-------|
| **Integration** | 3-4h | Combine Mini 6-9 code |
| **Database setup** | 1-2h | Task persistence |
| **Testing** | 2-3h | Unit + integration |
| **Monitoring** | 1-2h | Health checks, alerts |
| **Deployment** | 1-2h | Railway or AWS |
| **Total** | 12-15h | Complete project |

## ✅ Completion Checklist

### Code Quality
- [ ] All endpoints tested
- [ ] Error handling complete
- [ ] Logging structured (JSON)
- [ ] Retry logic working
- [ ] Tool registry extensible

### Features
- [ ] Task creation works
- [ ] Status tracking works
- [ ] Agent execution complete
- [ ] Multiple tools working
- [ ] Retries functioning

### Documentation
- [ ] README complete
- [ ] API documented
- [ ] Architecture diagram
- [ ] Deployment guide
- [ ] Examples provided

### Testing
- [ ] Unit tests (85%+ coverage)
- [ ] Integration tests
- [ ] Agent workflow tested
- [ ] Tool execution tested
- [ ] Error scenarios covered

### Deployment
- [ ] Docker works locally
- [ ] Environment vars configured
- [ ] Worker runs separately
- [ ] Deployed to Railway/AWS
- [ ] Health check passes

### Monitoring
- [ ] Health endpoint active
- [ ] Worker stats working
- [ ] Task tracking accurate
- [ ] Logs structured
- [ ] Alerts configured

## 📊 Expected Metrics

```
Throughput:
- Task creation: <10ms
- Task pickup: 50-200ms
- Average execution: 1-3 seconds
- Agent iterations: 1-5 per task

Reliability:
- Success rate: 95%+
- Worker availability: 99.9%
- Redis uptime: 99.99%

Quality:
- Agent decision accuracy: 90%+
- Tool execution success: 95%+
```

## 🎯 After Completion

### Portfolio Value
- ✅ Complex system (agents, queues, async)
- ✅ Production patterns (retries, monitoring)
- ✅ Scalable architecture
- ✅ Real-world use case

### Interview Topics
- ✅ Distributed task systems
- ✅ Agent reasoning patterns
- ✅ Queue management
- ✅ Error recovery strategies
- ✅ Scaling challenges

### Advanced Topics
- ✅ Multi-worker scaling
- ✅ Custom tools development
- ✅ Agent behavior tuning
- ✅ Cost optimization (LLM tokens)

## 📞 Support

- 📖 Check docs/ folder
- 🐛 Review troubleshooting above
- 💬 Check code comments
- 📝 Read docstrings

---

## Summary

**PROJECT 2: Agentic Backend**

| Aspect | Value |
|--------|-------|
| Integration | Mini 6-9 |
| Lines of Code | ~1800 |
| API Endpoints | 6-8 |
| Database Tables | 1 (tasks) |
| Queue System | Celery + Redis |
| Complexity | Advanced |
| Portfolio Value | ⭐⭐⭐⭐⭐ (150+ stars) |
| Interview Value | 🔥 Extremely High |

---

**Made as part of Sr Backend Roadmap** 🚀

Start: After Mini 6-9 complete (and Project 1 recommended)  
Duration: 12-15 hours  
Result: Production-ready agent system + advanced portfolio project