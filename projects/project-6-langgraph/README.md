# 🕸️ PROJECT 6: LangGraph

**A state machine whose state is saved after every step. Everything else follows.**

Project 5 left you with a loop that works and dies with its process. Restart, and
the conversation is gone. Deploy mid-run, and the run is gone. Pause for human
approval, and there is nowhere for the pause to live.

LangGraph fixes all three with one mechanism, and the interesting part is that it
really is one mechanism. Learn it and you can derive the API instead of
memorizing it.

## 📌 When to Start

**Prerequisites:** Project 5. You've met `create_agent` — which is itself built on
LangGraph — so this is opening up something you already used.

```
P4  LangChain Core                   LCEL, Runnable, retrieval
P5  LangChain Agents                 create_agent, tools, MCP, middleware
P6  LangGraph         ← estás aquí   estado durable, interrupt
P7  Deep Agents                      harness, tareas largas
P8  Agent Ops                        evals, monitoring, deploy
```

It also helps to have written crash recovery by hand at some point. If you have,
you already know the hard question isn't *how do I save state* — it's *what
exactly do I re-run after a crash*, and this project answers it differently than
you did.

## 🎯 The Core

**Not an agent library. A state machine whose state is persisted after every
step.** That single sentence generates every feature worth learning.

### 1. `StateGraph` — execution as a graph, not a loop

```python
from langgraph.graph import StateGraph, START, END

builder = StateGraph(State)
builder.add_node("call_model", call_model)
builder.add_node("run_tools", run_tools)
builder.add_edge(START, "call_model")

# The conditional edge IS the `if` at the top of your old while-loop.
builder.add_conditional_edges("call_model", should_continue, {
    "tools": "run_tools",
    "done": END,
})
builder.add_edge("run_tools", "call_model")

graph = builder.compile(checkpointer=checkpointer)
```

Your `while the model keeps asking for tools` becomes two nodes and one
condition. Nothing is gained by that alone — the gain is that a graph has *edges
between steps*, and an edge is a place where the runtime can stop.

### 2. The checkpointer — the reason everything else exists

State is written to Postgres after every node. Read this table as one cause and
five consequences:

| Because state is durable per step… | You get |
|---|---|
| …you can stop between nodes | **Safe cancellation**, with no half-finished tool call |
| …you can resume from the last one | **Crash recovery** without replaying completed work |
| …you can read it mid-run | **Progress**, queryable while it runs |
| …you can pause and wait | **`interrupt()`** — human-in-the-loop as a primitive |
| …you can read *old* ones | **Time travel** — replay from any past step |

None of these is a feature someone designed separately. They all fall out of the
same property. That's why this library rewards understanding over documentation.

### 3. `thread_id` — the unit of continuity

Every invocation names a thread; the graph picks up where that thread left off.
It's the conversation id you've always had, with the loading and the saving
already written.

### 4. `interrupt()` — a pause with somewhere to live

```python
from langgraph.types import interrupt, Command

def approve_step(state: State):
    # Execution stops here. The state is already on disk.
    decision = interrupt({"action": state["pending_action"]})
    return {"approved": decision == "yes"}

# Later — another process, another day:
graph.invoke(Command(resume="yes"), config={"configurable": {"thread_id": tid}})
```

In Project 5, approval was middleware that needed somewhere to store the paused
run. This is that somewhere. The pause survives the process, the deploy, and the
weekend.

## 🛑 What stays yours

| Still yours | Why |
|---|---|
| **The process boundary** | LangGraph runs in *your* process. That a worker invoked it is invisible to it. |
| **Per-tool idempotency** | Resuming skips completed **nodes**. It does not know `charge_card` charges a card. A tool that ran but didn't reach a checkpoint runs again. |
| **Budget across runs** | No budget concept. A counter shared across processes is a database problem. |
| **One source of truth** | **It makes this worse.** The checkpointer brings its own tables, so now you reconcile two states: yours and the graph's. |
| **Who approves what** | `interrupt()` is a mechanism. Which action deserves one is a business decision. |
| **The channel to the user** | Streaming happens inside the worker. Getting it back to an HTTP client is still polling or pub/sub. |

That fourth row is the honest cost of this project. You buy recovery and you pay
in reconciliation.

## 🏗️ Architecture

**Domain:** an operations agent that runs multi-step provisioning tasks — steps
that take real time, some of which need a human to say yes, none of which should
run twice.

```
POST /tasks → tasks table → queue → worker
                                      └─ graph.invoke(thread_id=task_id)
                                           ├─ checkpointer → Postgres
                                           └─ interrupt() → awaiting_approval
GET /tasks/{id} → your table (still the only thing the client reads)
```

Two tables, two owners. Yours answers the client; the checkpointer answers the
graph. Keeping that boundary clean is most of the work.

## 📚 Tech Stack

- **langgraph** — `StateGraph`, `interrupt`, streaming modes
- **langgraph-checkpoint-postgres** — `PostgresSaver`, the whole point
- **langchain-anthropic** — `claude-haiku-4-5`
- **FastAPI**, **PostgreSQL**, **Redis** — la API, el estado y la cola
- **LangSmith** — opcional, y aquí más útil que nunca: un run que se pausa y se
  reanuda tres días después es ilegible sin trazas

> Nota: el ReAct prebuilt que verás en tutoriales viejos (`create_react_agent` de
> `langgraph.prebuilt`) es el nombre antiguo. Post-1.0 el prebuilt es
> `create_agent`, el de Project 5. Aquí construimos el grafo a mano justamente
> para ver lo que ese prebuilt esconde.

## 🚀 Quick Start

```bash
uv sync
cp .env.example .env
docker compose up -d --wait
uv run alembic upgrade head          # tus tablas + las del checkpointer
uv run python -m app.worker
uv run uvicorn app.main:app --reload
```

## 🗺️ Phases

1. **The loop as a graph.** Two nodes, one conditional edge, `InMemorySaver`. No
   worker yet. Get the same behaviour you had in Project 5, written differently.
2. **`PostgresSaver`.** State durable per step. Go read the tables it created —
   that's where the second source of truth lives, and seeing it makes the
   reconciliation problem concrete instead of theoretical.
3. **Into the worker.** The API enqueues, the worker runs the graph. Notice how
   little the graph cares.
4. **`interrupt()`.** Approval that survives a restart. Approve one task, reject
   another, and resume both from a different process than the one that paused.
5. **Cancellation and progress.** Stop between nodes. Stream the steps out and
   answer "how's it going?" while it runs.
6. **Kill the worker mid-run.** `SIGKILL` in the middle of a turn, then resume the
   thread. **This is the experiment the whole project exists for** — and the
   question to answer precisely is *what got skipped and what got re-run*.
7. **What it doesn't cover.** Add per-tool idempotency and a cross-run budget.
   Notice they look exactly like they would in any other system, because they are
   database problems, not agent problems.

## 📊 What to record in APRENDIZAJES.md

| Question | Your answer |
|---|---|
| What resuming skipped, and what it re-ran | |
| Work lost to a `SIGKILL` mid-turn | |
| Tables you now own, and tables that own themselves | |
| Which state answers `GET /tasks/{id}`, and why | |
| Where a three-day-old pause physically lives | |
| What idempotency still had to solve | |

## ⏱️ Timeline

10-12 hours. Longer than the projects around it because `interrupt()` and
resume-after-crash are things you have to actually break to believe.

## ✅ Completion Checklist

- [ ] Agent running as a graph
- [ ] `PostgresSaver` wired, checkpoint tables inspected by hand
- [ ] Running inside a worker
- [ ] Approval via `interrupt()`, resumed from a different process, including a
      rejection
- [ ] Worker killed mid-turn and the thread resumed — verified, not assumed
- [ ] Idempotency and cross-run budget added
- [ ] `APRENDIZAJES.md` with the table filled in

## 🎓 You're done when you can answer

- Why does "state persisted per node" give you cancellation, recovery and
  approval all at once?
- What exactly did resuming a thread skip, and what did it re-run? Why that line?
- You now have two sources of truth. Which one answers the client, and what
  happens when they disagree?
- Which problems ported over unchanged from any ordinary backend, and what does
  that tell you about what LangGraph is actually for?
- Would you start a new agent project on this? Would you migrate an existing one?

See **[SOURCES.md](./SOURCES.md)** for official docs and related material.

---

**Made as part of Sr Backend Roadmap** 🚀

Duration: 10-12 h · Result: the ability to say what a framework costs, not just
what it does
