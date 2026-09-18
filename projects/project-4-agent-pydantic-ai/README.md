# 🧩 PROJECT 4: Agent on Pydantic AI

**The agent layer of Project 2, rebuilt with types doing the work.**

Project 2 hand-wrote a registry that derives JSON Schema from function signatures,
a `RunContext` that carries authenticated deps past the model, and history
serialization that keeps `tool_use`/`tool_result` pairs intact. Pydantic AI ships
all three. This project swaps them out and counts what's left.

It is deliberately the **shortest** of the framework projects: one layer, one
comparison, no infrastructure.

## 📌 When to Start

```
PROJECT 3 (LangChain)  →  PROJECT 4 (Pydantic AI)  →  PROJECT 5 (LangGraph)
   una llamada              un turno                     una corrida
```

That ordering is the point. LangChain abstracts **a call** and the retrieval
around it. Pydantic AI abstracts **a turn** — the model deciding, tools running,
the result coming back typed. LangGraph abstracts **a run** — many turns, paused,
resumed, surviving a crash. Each one is the previous plus state.

**Prerequisites:** Project 2 through its agent phases. You need `app/agent/` in
your head, because this project is a diff against it.

## 🎯 The Core: what Pydantic AI actually is

**A typed agent.** Dependencies, tool arguments and outputs are Python types, and
the framework does three things with them:

**1. Derives the contract.** `@agent.tool` reads the signature and the docstring
and produces the JSON Schema the model sees — the same trick as your registry,
maintained by someone else.

**2. Validates both directions.** Arguments coming in are validated against that
schema, and when the model sends something invalid it gets the error back and a
chance to fix it. Your registry treats invalid input as a permanent failure;
Pydantic AI treats it as a turn.

**3. Keeps identity out of the model's reach.** `RunContext[Deps]` with
`deps_type` is exactly your `AgentDeps`: the first parameter never appears in the
schema. You invented this pattern by hand; here it has a name and it is the
documented way.

Around that: usage limits, tools that require approval, message history you can
serialize and reload, structured outputs, and instrumentation.

**What it is not:** an orchestrator. There is no checkpointer, no durable state,
no notion of a run that survives your process. That is Project 5.

## 🔁 What it replaces from Project 2

| Project 2 (by hand) | Pydantic AI |
|---|---|
| `tools/registry.py` — schema from signature | `@agent.tool` |
| `deps.py` — `AgentDeps` + `RunContext` | `deps_type` + `RunContext[Deps]` |
| `agent/loop.py` — the `while stop_reason == "tool_use"` | `Agent.run_sync()` |
| `repository.dump_blocks` — history serialization | `all_messages_json()` / the message adapter |
| `budget.py` — the token ceiling | `UsageLimits` |
| `policy.py` + the pause | tools that require approval |
| Invalid tool input → permanent error | Validation error returned to the model, which retries |

Seven rows. That is why this project is short: the mapping is almost one to one,
and reading it is most of the lesson.

## 🛑 What it does NOT replace

| Still yours | Why |
|---|---|
| **The Celery task and the process boundary** | Pydantic AI runs in *your* process. That it's a worker is invisible to it. |
| **The `tasks` table and its state machine** | No status, no compare-and-swap, no idempotency key. |
| **Per-user budget** | `UsageLimits` is per run, in memory. Yours crosses conversations and workers. |
| **Retry classification and the DLQ** | It retries the model; it does not retry your task. |
| **Which tool is sensitive** | A business property. No framework decides it. |

## ⚠️ The one thing worth arguing about

Its message history is **its own representation**, not Anthropic's blocks — that
is what makes it provider-agnostic. So your rule *"the history is persisted
exactly as it travels"* stops being your rule and becomes a promise the framework
makes. It keeps that promise; but what sits in your `messages` table is no longer
what the API saw.

Deciding whether that trade is worth it is the actual output of this project.

## 📚 Tech Stack

- **pydantic-ai-slim[anthropic]** — the framework, with only the Anthropic model
  installed. The full `pydantic-ai` pulls every provider.
- **PostgreSQL** — the same tables, for the history
- **`claude-haiku-4-5`** — same model as Project 2, or the comparison is void

No FastAPI, no Celery, no Redis. This project is a script and a database.

## 🚀 Quick Start

```bash
uv sync
cp ../project-2-agentic-backend/.env .env
docker compose up -d --wait
uv run python -m app.demo "calculá 42 por 2"
```

## 🗺️ Phases

Four, and each one deletes something you wrote.

1. **One turn.** An `Agent` with `deps_type` and two tools ported from Project 2 —
   `calculate` and `get_my_orders`. Print the derived schema and check that
   `get_my_orders` still has `"properties": {}`.
2. **History.** Persist and reload a conversation across runs. This is where you
   see their representation and decide what you think of it.
3. **Limits and approval.** `UsageLimits` in place of `budget.py`; a tool that
   requires approval in place of `policy.py` and the pause.
4. **The count.** Fill in the table below.

## 📊 How you measure

| | Project 2 | Project 4 |
|---|---|---|
| Lines in the agent layer | | |
| Lines that survived unchanged | | |
| Files deleted outright | | |
| Time to add a new tool | | |
| Time to swap Anthropic for another provider | | |
| History in the DB is the API's blocks? | yes | no |

The last row is not a score. It is the trade, written down.

## ⏱️ Timeline

5-6 hours. Short by design: one layer, no infrastructure, and you already
understand every problem it solves.

## ✅ Completion Checklist

- [ ] Two tools ported, with `get_my_orders` still exposing an empty schema
- [ ] A conversation that survives across processes
- [ ] A run stopped by a usage limit
- [ ] A tool that waits for approval and then resumes
- [ ] `APRENDIZAJES.md` with the table filled in

## 🎓 You're done when you can answer

- Which seven pieces of your agent layer did it replace, and which five did it not?
- What does `deps_type` do that a plain argument cannot?
- What happens now when the model sends invalid tool arguments, and how is that
  different from what Project 2 does?
- What exactly is stored in `messages` now, and what did you give up to get it?
- Would you start a new agent on this? Would you migrate Project 2 to it?

---

**Made as part of Sr Backend Roadmap** 🚀

Start: after Project 3 · Duration: 5-6 h · Result: the shortest, sharpest of the
three framework comparisons
