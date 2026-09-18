# 🧠 PROJECT 7: Deep Agents

**Project 6 made a run survive a crash. This makes it survive forty steps.**

Durability is not the only way a long run fails. An agent can be perfectly
checkpointed and still lose the plot: it forgets the goal around step twelve, its
context window fills with tool output nobody needed, and by step thirty it's
confidently working on the wrong thing.

Deep Agents is LangChain's **harness** — the scaffolding that keeps a long task on
rails. Four capabilities, and every one of them is a systems problem wearing an
AI hat.

## 📌 When to Start

**Prerequisites:** Project 6. `deepagents` is, in its own docs, *"a standalone
library built on top of LangChain's core building blocks for agents"*, running on
the LangGraph runtime. Starting here would hand you a working agent with no way
to know what you were given.

```
P4  LangChain Core                   LCEL, Runnable, retrieval
P5  LangChain Agents                 create_agent, tools, MCP, middleware
P6  LangGraph                        estado durable, interrupt
P7  Deep Agents       ← estás aquí   harness, tareas largas
P8  Agent Ops                        evals, monitoring, deploy
```

There's a second prerequisite, and it's not a project: **you need to have watched
a long agent run go wrong**. If you haven't, these four capabilities read as a
list of imports. If you have, they read as answers.

## 🎯 The Core: four capabilities, four systems problems

| Capability | What it actually is |
|---|---|
| **Planning tool** | Externalizing the plan, because the model doesn't retain one |
| **File system** | Paging, applied to the context window |
| **Sub-agents** | Isolation, so the parent's context doesn't get polluted |
| **Memory** | State that outlives the conversation |

### 1. Planning — a to-do list the model has to maintain

Give an agent a tool for writing and updating a task list, and its trajectory on
hard problems improves. That is a strange sentence until you restate it: *the
model is bad at holding a plan in its head, so make it write the plan down.*

Nothing about the model changed. The scaffolding did. This is the cheapest
capability here and often the highest-leverage.

### 2. File system — the context window is not where work lives

An agent that reads three documents to answer a question does not need all three
in its context. It needs to read, extract, write a note, and move on.

```python
# The agent gets read/write/search tools over a backend you choose.
# What's in the window is a filename; what's on disk is the content.
```

This is paging. Working set in memory, everything else addressable on disk. The
backends are pluggable — local filesystem, a sandbox, object storage — and
choosing one is an ordinary infrastructure decision with ordinary tradeoffs
around isolation, persistence and blast radius.

### 3. Sub-agents — delegation for context hygiene, not just speed

The obvious reason to spawn sub-agents is parallelism. The better reason is
**isolation**: a sub-agent receives only the context for its subtask and returns
only a result. Whatever noise it waded through never reaches the parent.

An agent that searches twelve sources directly ends up with twelve sources of
noise in its window. One that delegates ends up with twelve summaries. The second
one is still coherent at step forty.

### 4. Memory and the system prompt

Memory that persists across conversations, loaded into the prompt. And the system
prompt itself as the place where the agent is *taught to use its tools* — in a
harness, prompt engineering stops being decoration and becomes configuration.

### Plus: context management

Summarization and skills — compacting a long history without losing the thread,
and packaging reusable procedures. This is where a long run either keeps working
or quietly degrades.

## 🛑 What stays yours

| Still yours | Why |
|---|---|
| **The sandbox boundary** | An agent with a filesystem and an interpreter can write and run code. What it can reach is a security decision, and it's yours. |
| **Cost control** | Sub-agents multiply calls. A task that fans out four ways costs more than four times a simple one. |
| **What "done" means** | A planning tool tracks steps. It does not know the answer is wrong. |
| **Deciding the decomposition** | Which subtasks exist, and what each sub-agent is allowed to do. |
| **Everything from Project 6** | Idempotency, reconciliation, the process boundary. A harness sits on top of those; it doesn't replace them. |

## 🏗️ Architecture

**Domain:** a research agent that produces a multi-source report. Chosen because
it is the shortest path to a task that genuinely doesn't fit in one context
window — it forces planning, intermediate files and delegation to earn their keep
rather than being demonstrated.

```
POST /research  →  deep agent
                     ├─ planning tool     → to-do state
                     ├─ filesystem        → notes/, sources/, draft.md
                     ├─ sub-agents        → one per source, isolated context
                     ├─ summarization     → compaction when history grows
                     └─ LangGraph runtime → durable, resumable (Project 6)
GET /research/{id}  →  progress, from the plan
```

## 📚 Tech Stack

- **deepagents** — el harness
- **langchain**, **langgraph** — debajo. No desaparecen: los sigues viendo
- **langchain-anthropic** — un modelo bueno planificando; aquí sí importa
- **PostgreSQL** — checkpoints y memoria de largo plazo
- Un **backend de filesystem** — local para empezar, sandbox después
- **LangSmith** — aquí deja de ser opcional en la práctica. Un run con subagentes
  tiene trazas anidadas, y leerlas a mano no es viable

## 🚀 Quick Start

```bash
uv sync
cp .env.example .env
docker compose up -d --wait
uv run python -m app.research "compare las tres opciones de pgvector index"
```

## 🗺️ Phases

1. **Bare agent, hard task.** Run a task that needs ten-plus steps with no
   harness at all. Watch it fail. **Write down how it failed** — that note is the
   baseline for everything below, and skipping this phase wastes the project.
2. **Planning.** Add the planning tool and only that. Re-run the same task. The
   delta is the lesson.
3. **Filesystem.** Give it read/write/search. Watch what it chooses to persist,
   and inspect the files afterwards — they're the agent's reasoning, externalized.
4. **Sub-agents.** Delegate per source. Compare the parent's final context window
   against phase 3's.
5. **Context management.** Summarization and skills on a task long enough that
   history compaction actually triggers.
6. **Memory.** State that survives across separate conversations.
7. **Sandbox it.** Move the filesystem to a sandboxed backend and decide, on
   purpose, what the agent can reach.

## 📊 What to record in APRENDIZAJES.md

| Question | Your answer |
|---|---|
| How the bare agent failed, in one sentence | |
| What the planning tool changed | |
| What the agent chose to write to disk | |
| Parent context size: with sub-agents vs without | |
| When summarization triggered, and what it dropped | |
| Cost of the same task at phase 1 vs phase 6 | |
| What you decided the sandbox may not touch | |

The cost row matters. A harness makes an agent capable, and it is not free.

## ⏱️ Timeline

8-10 hours. Half of it is phases 1 and 2, which look like the least code and
teach the most.

## ✅ Completion Checklist

- [ ] A documented failure of the bare agent on a long task
- [ ] Planning tool, with the before/after written down
- [ ] Filesystem, and its contents read after a run
- [ ] Sub-agents, with the context-size comparison measured
- [ ] Summarization triggered on a genuinely long run
- [ ] Memory across two separate conversations
- [ ] Filesystem moved to a sandboxed backend
- [ ] `APRENDIZAJES.md` with the table filled in

## 🎓 You're done when you can answer

- Why does writing the plan down improve a model that already "knows" the plan?
- The filesystem is paging. What's the working set, and who decides what's in it?
- What does context isolation buy that parallelism doesn't?
- At what point does summarization start costing you correctness?
- A harness makes an agent capable of more. What did it make harder?

See **[SOURCES.md](./SOURCES.md)** for official docs and related material.

---

**Made as part of Sr Backend Roadmap** 🚀

Duration: 8-10 h · Result: knowing why long agent runs fail, and the four known
countermeasures
