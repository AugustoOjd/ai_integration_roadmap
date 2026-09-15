# 🕸️ PROJECT 4: Agent on LangGraph

**Project 2, rebuilt on the framework — and honest about the half it doesn't touch.**

Project 2 built an agent that survives being run by a worker: persisted history,
idempotency, cooperative cancellation, crash recovery, unattended approval. This
project rebuilds it on LangGraph, which has a first-class primitive for about half
of that list — and nothing at all for the other half.

## 📌 When to Start

**Prerequisites:** Project 2 complete, through Phase 13.

```
Mini 6-9 → PROJECT 2 (by hand) ✅
                    ↓
              PROJECT 4 ← You are here
```

Project 2's Phase 13 already rewrites *one* phase on LangGraph as a taste test.
This project is the full version: the whole agent, deployed, with the hard
questions answered instead of noted.

## 🎯 The Core: what LangGraph actually is

Not an agent library. **A state machine whose state is persisted after every
step.** That single sentence generates every feature worth learning:

**1. `StateGraph` — execution as a graph, not a loop.** Nodes are steps, edges are
transitions, and conditional edges are the `if` that decides where to go next.
Your `while stop_reason == "tool_use"` becomes two nodes and one condition.

**2. The checkpointer — the reason the rest exists.** State is written to Postgres
after every node. Everything below is a consequence:

| Because state is durable per step… | You get |
|---|---|
| …you can stop between nodes | **Safe cancellation** with no orphaned `tool_use` |
| …you can resume from the last one | **Crash recovery** without replaying completed work |
| …you can read it mid-run | **Progress** you can query while it runs |
| …you can pause and wait | **`interrupt()`** — human-in-the-loop as a primitive |
| …you can read *old* ones | **Time travel** — replay from any past step |

**3. `thread_id` — the unit of continuity.** Every invocation names a thread;
the graph picks up where that thread left off. It's your `conversation_id`, with
the loading and saving already written.

That's the whole library. If you understand "state persisted per node", you can
derive the rest of the API instead of memorizing it.

## 🔁 What it replaces from Project 2

| Project 2 phase | LangGraph |
|---|---|
| **1** — history persistence, load/save per turn | Checkpointer, keyed by `thread_id` |
| **6** — trace readable while running | `get_state` / `get_state_history` + streaming modes |
| **7** — cancellation flag checked at the top of each iteration | Safe stop points between nodes, by construction |
| **8** — crash recovery, partial turn discarded | Resume from the last checkpoint — the partial turn is **kept**, not discarded |
| **9** — approval: pause, return, re-enqueue, resume | `interrupt()` and resume with a command |
| The loop in `agent.py` | `StateGraph`, or the prebuilt ReAct agent |

Phase 8 is the one that matters. It is the hardest part of Project 2 and the only
place in this whole comparison where a framework doesn't just rename your work —
it does something you couldn't reasonably build.

## 🛑 What it does NOT replace

| Still yours | Why |
|---|---|
| **Phase 2 — the process boundary** | LangGraph runs in *your* process. That it's a Celery worker is invisible to it. Serialization, the `fork`, and the `user_id` travelling in the payload are unchanged. |
| **Phase 5 — per-tool idempotency** | Resuming a thread skips completed *nodes*. It does not know `send_notification` sends mail. A tool that ran but didn't reach a checkpoint runs again. The `tool_use_id` key stays yours. |
| **Phase 10 — per-user budget** | No budget concept. A counter shared across workers is a database problem, not an agent problem. |
| **Phase 3 — one source of truth** | **It makes this worse.** The checkpointer brings its own tables. You now reconcile three states: Celery's backend, your `tasks` table, and the graph's. |
| **Who approves what** | Which tool is sensitive is a business property. No framework decides it. |
| **The channel to the user** | Streaming happens inside the worker. Crossing back to the HTTP client is still polling or pub/sub. |

## 🏗️ Architecture

Same infrastructure as Project 2. The worker's insides change; nothing else does.

```
POST /tasks → tasks table → Celery → worker
                                       └─ graph.invoke(thread_id=conversation_id)
                                            ├─ checkpointer → Postgres
                                            └─ interrupt() → pending_approval
GET /tasks/{id} → your table (still the only source of truth)
```

Keeping Celery is the point. Swapping it for LangGraph's own execution server
would test a different question, and it's the question Project 2 already answered
by choosing Celery over Temporal.

## 📚 Tech Stack

- **langgraph** — `StateGraph`, `interrupt`, streaming
- **langgraph-checkpoint-postgres** — `PostgresSaver`, against the same database
- **langchain-anthropic** — `ChatAnthropic` (`claude-haiku-4-5`, same as Project 2:
  the comparison is void if the model changes)
- **Celery + Redis**, **FastAPI**, **PostgreSQL** — unchanged from Project 2

## 🚀 Quick Start

```bash
uv sync
cp ../project-2-agentic-backend/.env .env
docker compose up -d
uv run alembic upgrade head          # your tables + the checkpointer's
uv run celery -A app.celery_app worker --loglevel=info
uv run uvicorn app.main:app --reload
```

## 🗺️ Phases

1. **The loop as a graph** — two nodes (call model, run tools), one conditional
   edge. In-memory checkpointer. No Celery yet, same as Project 2's Phase 0.
2. **`PostgresSaver`** — state durable per step. Inspect the tables it creates;
   that's where the third source of truth lives.
3. **Into the worker** — Celery calls the graph. Phase 2 of Project 2 all over
   again, unchanged, which is the lesson.
4. **`interrupt()`** — approval, replacing the pause/resume pair.
5. **Cancellation and progress** — stop between nodes, stream the steps out.
6. **Kill the worker mid-run** — and resume the thread. This is the experiment
   the whole project exists for.
7. **Keep what it doesn't cover** — port idempotency and the per-user budget over
   untouched, and notice that they port without a single change.

## 📊 How you measure

| | Project 2 | Project 4 |
|---|---|---|
| Lines in the agent layer | | |
| Lines that survived unchanged | | |
| Tables owned | | |
| Recovery after `SIGKILL` mid-turn | discard partial turn, `failed` | resume from checkpoint |
| Work lost on recovery | one turn | one node |
| States to reconcile | 2 | 3 |

The bottom three rows are the trade, stated plainly. You buy recovery and pay in
reconciliation.

## ⏱️ Timeline

10-12 hours. Longer than Project 3 because `interrupt()` and resume-after-crash
are things you have to actually break to believe.

## ✅ Completion Checklist

- [ ] Agent loop running as a graph
- [ ] `PostgresSaver` wired, checkpoint tables inspected
- [ ] Running inside the Celery worker
- [ ] Approval via `interrupt()`, end to end including rejection
- [ ] Worker killed mid-turn and the thread resumed — verified, not assumed
- [ ] Idempotency and per-user budget ported over
- [ ] `APRENDIZAJES.md` with the comparison table filled in

## 🎓 You're done when you can answer

- Why does "state persisted per node" give you cancellation, recovery and
  approval all at once?
- What exactly did resuming a thread skip, and what did it re-run?
- Which Project 2 phases came across without a single line changed, and what does
  that tell you about what LangGraph is for?
- You now have three sources of truth. Which one answers `GET /tasks/{id}`, and why?
- Would you start a new agent project on this? Would you migrate an existing one?

---

**Made as part of Sr Backend Roadmap** 🚀

Start: after Project 2 · Duration: 10-12 h · Result: the ability to say what a
framework costs, not just what it does
