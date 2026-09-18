# 🤖 PROJECT 2: Agentic Backend

**An agent that survives being run by a worker.**

Mini 9 built an agent loop that runs inside a request: you send a message, the
loop reasons and calls tools, you get an answer. This project moves that loop
into a Celery worker — and everything that was implicit becomes a problem you
have to solve on purpose.

## 📌 When to Start

**Prerequisites:** Mini 6-9 complete.

```
Mini 6 → Mini 7 → Mini 8 → Mini 9 ✅
                              ↓
                         PROJECT 2 ← You are here
```

Read **[ANTES_DE_EMPEZAR.md](./ANTES_DE_EMPEZAR.md)** before writing a line. Half
the decisions in this project have to be made up front, because afterwards they
are refactors.

## 🎯 What changes when the loop leaves the request

One line changes — `execute_agent_task.delay(id)` instead of `run_agent(...)` —
and these stop being free:

| In a request | In a worker |
|---|---|
| The exception becomes an HTTP code | There is nobody to tell |
| The 202 goes back to whoever asked | Nobody is waiting for it |
| Running once means running once | The broker **will** deliver twice |
| The process is alive until it answers | It can die mid-turn |
| Progress is "wait for the response" | Someone asks "how's it going?" at 4 seconds |

The whole project is those five rows. The agent itself barely changes.

## 🏗️ Architecture

```
POST /conversations/{id}/tasks ──> tasks (pending) ──> Redis ──> worker
        202 + task_id                                              │
                                                    ┌─────────────┘
GET /tasks/{id} <── tasks table                     │
   (the ONLY channel)                               ├─ run_agent → Anthropic
                                                    ├─ tools → Postgres
                                                    └─ state → tasks table
```

**The `tasks` table is the single source of truth.** Celery's result backend is a
transport detail: it does not know `pending_approval`, it does not survive a
`FLUSHDB`, and its `PENDING` is indistinguishable from a made-up id. No endpoint
in this app constructs an `AsyncResult`.

## 📚 Tech Stack

- **Python 3.12**, **uv** — same as every mini
- **FastAPI** + **uvicorn**
- **SQLAlchemy 2.x, synchronous** + **psycopg 3** — *not* async, and that is the
  first decision of the project: Celery tasks are synchronous functions
- **Alembic** — the schema changes in six of the twelve phases
- **PostgreSQL 17**
- **Celery 5.5 + Redis** — broker, result backend, and a third database for the
  dead letter queue
- **Anthropic** `claude-haiku-4-5` — same model as Mini 9, or comparisons are void
- **No LangChain, no Pydantic AI, no LangGraph.** The registry and the loop are
  yours. Those rewrites are Projects 3, 4 and 5.

## 🚀 Quick Start

```bash
cd projects/project-2-agentic-backend
cp .env.example .env            # put your ANTHROPIC_API_KEY in it
uv sync
docker compose up -d --wait     # postgres + redis

uv run alembic upgrade head
uv run python -m scripts.seed_orders
```

Then four windows:

```bash
uv run uvicorn app.main:app --reload                          # the API
uv run celery -A app.tasks.celery_app worker --loglevel=info  # the worker
uv run celery -A app.tasks.celery_app beat   --loglevel=info  # the clock
docker compose exec postgres psql -U agentic -d agentic_backend
```

The worker window is half the learning: the loop prints every iteration, every
tool call and every token count as it goes.

`beat` is a separate process and it is easy to forget. Without it the reaper
never runs, orphaned tasks pile up silently, and **everything else keeps working
perfectly** — which is what makes it the hardest failure mode here to notice.

Celery has no `--reload`. After any code change, restart the worker by hand.

## 📝 API

Every endpoint except `/health` requires an `X-User-Id` header. It's scaffolding
for a token — but the *shape* is real: the owner arrives through a channel the
model never sees.

```
POST /conversations                        open a thread
POST /conversations/{id}/tasks             202 + task_id
GET  /tasks/{id}                           status, progress, what needs approving
GET  /tasks?status=running                 the list
POST /tasks/{id}/approvals/{tool_use_id}   decide, and re-enqueue the run
POST /tasks/{id}/cancel                    cooperative, idempotent
GET  /users/me/budget                      what is left in this window
GET  /conversations/{id}/log               the audit trace
```

`POST /conversations/{id}/tasks` returns **202, not 201**: what comes back is not
the result, it's a promise. `GET /tasks/{id}` is then the only channel — the
result, the error, the pause and the progress are told there or not at all.

There is also a synchronous door, `POST /conversations/{id}/messages`, kept from
Phase 0: it runs the agent inside the request and leaves no `tasks` row. Useful
for debugging against the queue-less baseline.

## 📂 Layout

```
app/
├── main.py              entrypoint
├── core/       config.py · db.py · models.py
├── agent/      loop.py · deps.py · repository.py · budget.py
│               context.py · policy.py · llm.py
├── tools/      registry.py · idempotency.py
│               calculator · clock · orders · search
├── tasks/      celery_app.py · agent_tasks.py · state.py · reaper.py
│               retry_policy.py · base_task.py · dead_letter.py
└── api/        errors.py · routes/ · schemas/
```

Dependencies point one way:

```
api  →  agent  →  core
         ↓
       tools  →  core
```

`core` imports nothing from the other layers, and **`agent` knows nothing about
HTTP** — which is exactly the property that lets a Celery worker call
`run_agent` without a request in sight.

## 🗺️ Phases

Twelve, built one at a time and never leaving the app broken in between. Full
plan in **[FASES.md](./FASES.md)**.

| | | |
|---|---|---|
| 0 | Mini 9 ported to synchronous, no queue | ✅ |
| 1 | Conversations and tasks; the agent runs in the request | ✅ |
| 2 | Celery in the middle: the process boundary | ✅ |
| 3 | One source of truth: the state is your table | ✅ |
| 4 | Retries: what gets retried and what doesn't | ✅ |
| 5 | Idempotency: the task that runs twice | ✅ |
| 6 | Progress: the trace readable while it runs | ✅ |
| 7 | Cooperative cancellation | ✅ |
| 8 | The worker that dies: heartbeat and reaper | ✅ |
| 9 | Approval with nobody watching | ✅ |
| 10 | Per-user budget | ✅ |
| 11 | Full manual pass + CHECK_LEARNING | ✅ |

## 🔬 Verification

**There is no automated test suite, and that is a decision.** A green `assert`
tells you the invariant holds; it doesn't teach you what breaks it, what the
breakage looks like, or why the design is shaped this way.

**[PRUEBAS.md](./PRUEBAS.md)** has three checks per phase, each in four parts:
*Correr* → *Observar* → *Por qué* → ***Rompelo***. The last one is the point —
you break it on purpose and watch the mechanism become visible.

**[CHECK_LEARNING.md](./CHECK_LEARNING.md)** gathers every question. If you can
answer them without opening the code, the project did its job.

The cost of that choice is stated in Phase 11: no regression net, no CI, and
race conditions that are awkward to reproduce by hand. The goal here is to
understand, not to maintain.

## 🚫 Out of scope

The project ends at Phase 11: a system that runs on your machine, that you
understand, and that you know how to break. **It is not deployed.**

Terraform, Railway, CI and Flower are deliberately out — that is infrastructure,
not agents, and none of it teaches anything about this project's actual problem.
Written down so it reads as a decision and not an omission: **this project does
not demonstrate that you can deploy.** What it demonstrates is idempotency,
cooperative cancellation and crash recovery, which are considerably harder to
learn than a `terraform apply` and considerably rarer to find.

## ⏱️ Timeline

18-22 hours. The original estimate of 12-15 was written before idempotency,
cancellation and crash recovery were in scope.

## 🔗 What comes after

```
PROJECT 3 (LangChain)  →  PROJECT 4 (Pydantic AI)  →  PROJECT 5 (LangGraph)
   una llamada              un turno                     una corrida
```

Project 4 rewrites this project's `app/agent/` layer; Project 5 rewrites its
persistence, pause and recovery phases. Each phase here ends with a
*"Cómo lo resuelven los frameworks"* note pointing at what those projects will
measure.

---

**Made as part of Sr Backend Roadmap** 🚀
