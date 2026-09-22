# 🧩 PROJECT 3: Agent on Pydantic AI

**An ecosystem where the type is the contract.**

You've written an agent loop by hand: a registry that turns functions into JSON
Schema, a context object that carries authenticated dependencies past the model,
history serialization that keeps tool calls and their results paired. You know
what those parts cost.

Pydantic AI is a different answer to the same problem: **declare the types and let
the framework derive everything else**. This project is a self-contained look at
that ecosystem — what it does, what it buys you, and what it charges.

> 📋 The phase-by-phase plan lives in **[FASES.md](./FASES.md)**. It splits the
> work in two: **deep** on the typed agent, which is what P3 is actually about,
> and a **shallow pass** over the rest of the ecosystem — embeddings, MCP, evals,
> graphs, interfaces — each of which gets its own project later in the roadmap.

## 📌 When to Start

**Prerequisites:** Project 2 complete. You need the agent loop in your head, not
on screen — this project doesn't diff against it.

It goes first among the framework projects because it is **one layer, one
library, minimal infrastructure**: no worker, no queue, no HTTP.

```
Projects 1-2 (por tu cuenta)   la base
      ↓
P3  Pydantic AI      el agente tipado          ← estás aquí
      ↓
P4  LangChain Core   LCEL, Runnable, RAG
P5  LangChain Agents create_agent, MCP, middleware
P6  LangGraph        estado durable, interrupt
P7  Deep Agents      harness, tareas largas
P8  Agent Ops        evals, monitoring, deploy
```

P3 stands apart on purpose. Pydantic AI is a **competing ecosystem**, not a step
on the LangChain ladder. Seeing it first means you meet the LangChain track with
something to compare against — at the level of philosophy, not line counts.

## 🎯 The Core: typed end to end

The pitch is one sentence: *move whole classes of errors from runtime to
write-time*. Four mechanisms deliver it.

### 1. The signature is the schema

```python
from dataclasses import dataclass
from pydantic_ai import Agent, RunContext

@dataclass
class Deps:
    """Everything the tools need and the model must never see."""
    db: Connection
    customer_id: str          # comes from your auth, not from the model

agent = Agent(
    "anthropic:claude-haiku-4-5",
    deps_type=Deps,           # binds RunContext[Deps] for every tool
    instructions="You triage support tickets. Be terse.",
)

@agent.tool                   # reads the signature AND the docstring
async def recent_orders(ctx: RunContext[Deps], limit: int = 5) -> list[Order]:
    """List the customer's most recent orders."""
    return await ctx.deps.db.orders(ctx.deps.customer_id, limit)
```

The JSON Schema the model sees is derived from `limit: int = 5` and that
docstring. Nothing is written twice, so nothing can drift.

### 2. `RunContext[Deps]` — identity the model cannot reach

`ctx` is the first parameter and **never appears in the schema**. The model can
ask for `recent_orders(limit=3)`; it cannot ask for someone else's orders,
because `customer_id` isn't an argument — it's a dependency you injected.

This is the security property worth internalizing: *anything the model can name,
it can lie about*. Dependency injection is how you keep things out of its reach.

### 3. Validation is bidirectional, and a failure is a turn

```python
@agent.tool
async def refund(ctx: RunContext[Deps], order_id: str, amount: Decimal) -> str:
    """Refund an order. Amount must not exceed the order total."""
    order = await ctx.deps.db.order(order_id)
    if amount > order.total:
        # Not an exception: the model gets the message and tries again.
        raise ModelRetry(f"Max refundable for {order_id} is {order.total}")
    ...
```

Arguments are validated against the derived schema on the way in. When the model
sends something invalid, the error goes **back to the model** as another turn
instead of ending the run. A hand-written registry usually treats bad tool input
as a permanent failure; here it's a conversation.

### 4. `output_type` — the run returns an object, not a string

```python
class Triage(BaseModel):
    category: Literal["billing", "shipping", "technical"]
    priority: int = Field(ge=1, le=5)
    needs_human: bool
    summary: str

agent = Agent("anthropic:claude-haiku-4-5", deps_type=Deps, output_type=Triage)

result = await agent.run("My package never arrived and I was charged twice")
result.output.priority   # an int between 1 and 5, validated, typed
```

This is the part that changes how an agent fits into a backend. A validated
object drops straight into a database write or an `if`. No parsing, no "please
respond in JSON", no defensive `try: json.loads(...)`.

### 5. Toolsets — the tool set is a value you compose

A tool is a function; a **toolset** is a collection you can do algebra on.

```python
# Which tools this caller sees is decided per run, not inside each tool.
toolset = FunctionToolset(tools=[recent_orders, refund])

agent = Agent(
    "anthropic:claude-haiku-4-5",
    deps_type=Deps,
    # Only support agents ever see `refund` in the schema. Not a check inside
    # the tool — the tool is not there at all.
    toolsets=[
        toolset.filtered(
            lambda ctx, tool_def: ctx.deps.role == "agent" or tool_def.name != "refund"
        )
    ],
)
```

Chainable: `.filtered(predicate)` · `.prefixed("weather")` for namespacing ·
`CombinedToolset([a, b])` to merge · a `WrapperToolset` subclass overriding
`call_tool` to wrap every call with your own logic · `ApprovalRequiredToolset`.

In Project 2, "which tools does this user get" was an `if` at the top of every
tool body. Here it's a value you build before the run starts.

### Around those five

`UsageLimits` — a ceiling per run on requests, output tokens, tool calls, and
**cost** (`cost_limit=Decimal("0.01")`) · tools that require approval · message
history you can serialize and reload · `RunContext.enqueue()` to inject a
follow-up message mid-run · durable execution through Temporal, DBOS or Prefect ·
OpenTelemetry-native instrumentation via Logfire.

And one category that is neither tool nor toolset: **capabilities**
(`capabilities=[MCP(...), ImageGeneration(...)]`) — features the framework
resolves natively-or-by-fallback depending on the provider. The most opinionated
abstraction in the library, and the one that ties you down the most.

## 🤝 Human-in-the-loop, the typed way

Its approval model is worth studying on its own because it's unusually clean:

```python
@agent.tool(requires_approval=True)
async def refund(...): ...

# DeferredToolRequests must be a valid outcome of the run.
agent = Agent(..., output_type=[Triage, DeferredToolRequests])
```

A run that reaches a gated tool **ends** with a `DeferredToolRequests` holding
the pending calls — tool name, validated arguments, call id. You approve or
reject each one (`ToolApproved()` / `ToolDenied(message=...)`), build a
`DeferredToolResults`, and run again with the prior history. Approved calls
execute, rejected ones feed your message back to the model, and the run continues.

The pause is **a value in the type system**, not a flag in a database. Compare
that with whatever you did in Project 2.

> ⚠️ Worth writing down: approval stops the *model* from acting unsupervised. It
> does not authorize anything. The tool body still runs whenever the call reaches
> it, so authorization belongs inside the function — same as it always did.

## 🛑 What stays yours

| Still yours | Why |
|---|---|
| **The process boundary** | It runs in *your* process. That a worker invokes it is invisible to the library. |
| **Task state and idempotency** | No status machine, no compare-and-swap, no idempotency key. A tool that sends mail will send it twice if you run it twice. |
| **Budget across runs** | `UsageLimits` is per run, in memory. A ceiling that spans conversations and processes is a database problem. |
| **Which tool is sensitive** | `requires_approval=True` is a switch. Deciding which tools get it is a business decision. |
| **Retry classification** | It retries the *model*. It does not retry your job. |

## ⚠️ The one thing worth arguing about

Its message history is **its own representation**, not the provider's blocks.
That is exactly what makes it provider-agnostic — and it means what you persist
is no longer what the API saw. If you ever had a rule like *"the history is
stored exactly as it travels"*, that rule stops being yours and becomes a promise
the framework makes. It keeps the promise. But you can no longer replay a run
against the raw API from your own table.

Deciding whether that trade is worth it is the actual output of this project.

## 🏗️ Architecture

Deliberately small. No FastAPI, no Celery, no Redis: a script and a database.

```
CLI → Agent(deps_type=Deps, output_type=Triage)
        ├─ toolsets  → filtered per caller → PostgreSQL (orders, customers)
        ├─ approval  → DeferredToolRequests → you → DeferredToolResults → resume
        ├─ model     → claude-haiku-4-5, behind a FallbackModel
        ├─ history   ⇄ messages table (its representation, not the provider's)
        └─ logfire   → spans per turn, per tool call, per validation retry

        and, one afternoon each, off to the side:
        agent.iter() · pydantic-graph · Embedder · MCP · clai · evals
```

## 📚 Tech Stack

- **pydantic-ai-slim[anthropic]** — the framework with only one provider
  installed. Plain `pydantic-ai` pulls every provider in existence.
- **`claude-haiku-4-5`** — small, fast, good at tool calling. The project is
  about types, not about model quality.
- **PostgreSQL** — orders, customers, and the serialized history
- **logfire** — OpenTelemetry-native tracing that shows each turn, each tool call
  and each validation retry
- **pydantic-graph**, **pydantic-evals** — separate packages, used briefly in the
  shallow pass. They ship with the ecosystem but are not what P3 is about.

## 🚀 Quick Start

```bash
uv sync
cp .env.example .env          # ANTHROPIC_API_KEY, DATABASE_URL
docker compose up -d --wait
uv run python -m app.seed     # a handful of fake customers and orders
uv run python -m app.schema   # the derived JSON Schema, no API call
uv run python -m app.cli "mi paquete nunca llegó y me cobraron dos veces"
```

## 🗺️ Phases

Sixteen, most of them small. Full plan and dependencies in
**[FASES.md](./FASES.md)**.

### Part A — The typed agent (build it, break it, verify it)

0. **Skeleton.** `uv`, Postgres, seed, `.env`. No agent yet.
1. **One run, one type.** An `Agent` with `deps_type` and `output_type=Triage`.
   Print the derived JSON Schema for your tools and confirm `ctx` is absent from
   it — that absence is the whole dependency-injection idea, made visible.
2. **Tools with teeth.** `recent_orders` and `refund` against real rows. Make the
   model send an invalid amount on purpose and watch `ModelRetry` turn a failure
   into another turn.
3. **Toolsets.** Decide which tools *this* caller sees, without a single `if`
   inside a tool body. Print the schema twice, for two different callers.
4. **History.** Serialize a conversation, reload it in a fresh process, continue
   it. Open the stored JSON and look at what's actually in there. This is where
   you form an opinion about the trade above.
5. **Models and providers.** `FallbackModel`, `model.profile`, and actually
   swapping the provider — because the table below asks how long that took.
6. **Limits and approval.** `UsageLimits` to cap a run; `requires_approval=True`
   on `refund`, then the full `DeferredToolRequests` → approve/deny →
   `DeferredToolResults` → resume cycle, including a rejection.
7. **Instrument it.** Wire Logfire and re-run phase 6. Seeing a validation retry
   as a span is the fastest way to understand what the loop is really doing.

### Part B — The ecosystem (a look, not a build)

Functionality only. No infrastructure — each of these has its own project later.

8. **Under the hood.** `agent.iter()`: the run you've been doing is a graph.
   `UserPromptNode` → `ModelRequestNode` → `CallToolsNode` → `End`.
9. **`pydantic-graph` on its own.** A small graph of your own, and its
   auto-generated Mermaid diagram.
10. **`Embedder`.** `embed_query` vs `embed_documents`, and why they differ.
11. **MCP.** `capabilities=[MCP(url=...)]` — tools that are not functions in your
    process. You consume a server; you don't write one.
12. **Interfaces.** `agent.to_cli_sync()`, `clai web`, and
    `run_stream_events()`. The same agent, three surfaces.
13. **Image generation.** One capability the model decides to use on its own.
14. **`pydantic-evals`.** Three cases, one `LLMJudge`, and one evaluator that
    grades the **trajectory** instead of the answer.

### Part C

15. **Close it out.** Full manual verification and `APRENDIZAJES.md`.

## 📊 What to record in APRENDIZAJES.md

| Question | Your answer |
|---|---|
| What's in the derived schema for each tool, and what isn't | |
| What happened when the model sent invalid arguments | |
| How you decided which tools each caller sees | |
| What the serialized history actually contains | |
| Time to swap the model provider | |
| How a pause is represented, and where it lives | |
| Time to add a new tool | |
| What you'd still have to build to run this in a worker | |
| What the ecosystem tied you to, and what it saved you | |

The second-to-last row is the honest one. Everything above it is what you were
given.

## ⏱️ Timeline

11-13 hours, split in two:

| Part | Hours | What it is |
|---|---|---|
| A — The typed agent | 6-7 | The project proper. One layer, almost no infrastructure, and every problem it solves is one you've already met. |
| B — The ecosystem | 4-5 | A guided tour. Enough to have an opinion when these come back as full projects. |
| C — Close it out | 1 | Verification and `APRENDIZAJES.md`. |

If you only have an afternoon, Part A alone is a complete project. Part B is
additive and can be dropped without leaving a hole.

## ✅ Completion Checklist

**Part A**

- [ ] Two tools whose schema you printed and read
- [ ] `output_type` returning a validated object you write straight to the DB
- [ ] An invalid tool call recovered via `ModelRetry`
- [ ] The same agent showing two different tool sets to two different callers
- [ ] A conversation that survives across processes
- [ ] The same run against a second provider, with the diff noted
- [ ] A run stopped by `UsageLimits`
- [ ] A gated tool approved, and another one denied, both resumed
- [ ] Logfire showing the turns of a single run

**Part B**

- [ ] A run stepped through node by node with `agent.iter()`
- [ ] A graph of your own, rendered as Mermaid
- [ ] One embedding you looked at, from `embed_query` and `embed_documents`
- [ ] One MCP tool called from your agent
- [ ] The agent talked to from the CLI and from the browser
- [ ] One generated image
- [ ] Three eval cases run, one of them grading the trajectory

**Part C**

- [ ] `APRENDIZAJES.md` with the table filled in

## 🎓 You're done when you can answer

- Why does `RunContext` keep `customer_id` out of the model's reach, and what
  would break if it were a plain argument?
- What is the difference between raising `ModelRetry` and raising anything else?
- What exactly is stored when you serialize the history, and what did you gain
  and lose by it not being the provider's blocks?
- A pause here is a return value. What does representing it that way make easy,
  and what does it make hard?
- Why is a toolset a better answer than a check inside each tool, and when is it
  a worse one?
- An `Agent` is a `pydantic-graph` underneath. What did seeing the nodes change
  about how you think of the loop?
- What is a *capability*, and why is it neither a tool nor a toolset?
- Would you start a new agent on this? What would stop you?

See **[SOURCES.md](./SOURCES.md)** for official docs and related material.

---

**Made as part of Sr Backend Roadmap** 🚀

Start: after Project 2 · Duration: 11-13 h (Part A alone: 6-7 h) · Result: a
working opinion about what types buy you in an agent, and a map of the ecosystem
around it, before meeting LangChain
