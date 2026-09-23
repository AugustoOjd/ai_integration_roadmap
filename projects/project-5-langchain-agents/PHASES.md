# 🗺️ PROJECT 5 — Phase plan

> **Status:** plan index. Each phase gets detailed when we start it.

The README describes 6 phases and 8-10 hours. This plan uses the same rule as P4:

- **Build** whatever involves a *decision* you'll have to make again. Run it,
  break it, verify it.
- **Document** in `CONCEPTS.md` whatever is an *API shape* you'll look up when
  you need it. Short snippet, what it's for, what it groups with, when not to
  use it, and its equivalent in what you already know.

**Budget: 6-7 hours** instead of 8-10.

---

## The main thread

**A loop that isn't yours, and the doors back in.**

In mini 9 and P2 you wrote the `while` yourself: every decision (when to stop,
what to log, how much to spend) was a line of yours in the middle of the loop.
Here `create_agent` hands it to you closed. Every phase asks the same question:
*that line I used to write inside the loop — where does it live now?*

There are three possible answers: **middleware** (cross-cutting to the loop),
**tool** (inside one action) or **outside the agent** (process, durable state,
business rules). Telling them apart is what you take away from the project.

---

## Phases

### Part A — Build (6-7 h)

| Phase | Topic | Depends on |
|------|------|-----------|
| 0 | Skeleton: `uv`, Postgres (orders, customers), `.env`, seed | — |
| 1 | `create_agent` with two read-only tools. Print the schema the model sees | 0 |
| 2 | Memory: `InMemorySaver` + `thread_id`. Three turns, restart, watch it forget | 1 |
| 3 | Custom middleware: `BudgetMiddleware` (`wrap_model_call`) + audit (`after_model`) | 1 |
| 4 | MCP: server with the SDK, **hand-written client** over stdio reading raw JSON-RPC. Then the adapter | 1 |
| 5 | HITL: `HumanInTheLoopMiddleware` on `issue_refund`. Approve, reject, edit | 2, 3 |
| 6 | Break it: kill the MCP server mid-run, exceed the budget mid-run | 3, 4 |
| 7 | Wrap-up: manual verification + `LEARNINGS.md` | all |

### Part B — Document in `CONCEPTS.md`

| Topic | Why it isn't built |
|---|---|
| Decorator-style middleware (`@before_model`, `@wrap_tool_call`…) | It's the class form as a function. Writing two classes is enough. |
| Built-ins: `SummarizationMiddleware`, tool retry, model fallback, rate limit, PII | You *read* them (their source is the best documentation of the hooks), you don't reimplement them. One or two may come in for free in phase 3 if needed. |
| `response_format` / agent structured output | You already did it with `output_type` in P3. Same idea, different name. |
| `agent.stream()` with `stream_mode` | P4's streaming applied to a graph: a snippet is enough to understand it. |
| Dynamic prompt and `context_schema` | Configuration API, look it up when needed. |
| Multi-agent (one agent as another's tool) | That's P7 for real. Here it's enough to know it's just another tool. |
| LangSmith | Logfire under another name; you instrumented it in P3. |

Each entry uses the same format as P4 (what it's for / groups with / snippet /
when NOT to use it / what this was in earlier projects).

---

## Decisions, already made

| # | Question | Answer | Phase |
|---|---|---|---|
| 1 | Model? | **Anthropic** `claude-haiku-4-5`, same as P4. Fast and good at calling tools. | 0 |
| 2 | Domain? | **Nordix**, the fictional company from P4: now with orders and customers. P4's policies (refunds, shipping) give meaning to the rules in `issue_refund`. | 0 |
| 3 | Async or sync? | **Async**. The MCP client is async no matter what; mixing both modes is worse than picking one. | 0 |
| 4 | Postgres access? | **`psycopg` 3 async + pool**, hand-written SQL. Three tables and four queries: an ORM doesn't pay off here. | 0 |
| 5 | Interface? | **CLI** (`python -m app.chat`), no FastAPI. HITL in a terminal is an `input()`; over HTTP it's a state problem that belongs to P6. | 0 |
| 6 | Which tools are local and which remote? | **Local:** `order_status`, `customer_orders`, `issue_refund` (your DB). **Remote (MCP):** a carrier tracking service — something that in real life *isn't yours*. | 1, 4 |
| 7 | MCP transport? | **stdio**. Easiest to read raw: one line of JSON per message. HTTP gets documented. | 4 |
| 8 | What gets hand-written in MCP? | The **client** (`initialize` → `tools/list` → `tools/call`). The server uses **`fastmcp`** — the library `MCPAdapter` is built on, so one MCP stack instead of two. The part worth understanding is the protocol on the wire, not the server's dispatch. | 4 |
| 9 | Checkpointer? | **`InMemorySaver`**. On purpose: its amnesia is the argument for P6. | 2 |
| 10 | Automated tests? | No. Manual verification, same as P2, P3 and P4. | 7 |

> **Verified in phase 4:** `langchain.mcp.MCPAdapter` exists in `langchain`
> 1.4.2. It's in beta (importing it emits `LangChainBetaWarning`) and ships
> behind the `mcp` extra, which requires `fastmcp>=4,<5`. The older separate
> package, `langchain-mcp-adapters` (`MultiServerMCPClient`), isn't used.

---

## What you'll learn

1. **`create_agent` returns a compiled graph.** `invoke`, `stream`, the
   checkpointer and `thread_id` come from LangGraph, not LangChain. P6 isn't an
   extra: it's opening up what you're already using.

2. **Middleware is inversion of control over someone else's loop.**
   `before_*` / `after_*` are *nodes* (they look at and modify state); `wrap_*`
   go *around* (they control whether the call happens and see both ends).
   Picking the wrong hook is the typical mistake.

3. **A remote tool is a network dependency.** Discovery, timeouts, server
   version, what happens when it's down. None of it has to do with LLMs.

4. **Approving isn't authorizing.** HITL stops the *model*. The body of
   `issue_refund` still has to validate amount, order status and idempotency —
   because a tired human also approves twice.

5. **A pause needs somewhere to live.** HITL works with `InMemorySaver` until
   the process dies. That limit is the exact boundary between P5 and P6.

---

## What this project does NOT do

- **Nothing outlives the process.** Durable state is P6.
- **No HTTP API or worker.** You already solved that in P2; here it would only
  add noise.
- **No line-by-line comparison with the P2 loop.** What gets compared is
  *where* each concern lives.
- **No evals.** That's P8.

---

## ⏱️ Timeline

| Part | Hours |
|---|---|
| A — build | 6-7 |
| B — document | written in parallel |
| **Total** | **6-7** |

---

## 📊 LEARNINGS table

| Question | Phase |
|---|---|
| What the derived tool schema contains, and what it omits | 1 |
| Which concerns from the P2 loop became middleware | 3 |
| Which hook you picked for each thing, and why that one | 3 |
| What the raw MCP exchange looks like, before any client | 4 |
| Where a paused run lives, and what kills it | 5 |
| What broke when the MCP server went away | 6 |
