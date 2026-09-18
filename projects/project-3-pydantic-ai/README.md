# 🧩 PROJECT 3: Agent on Pydantic AI

**An ecosystem where the type is the contract.**

You've written an agent loop by hand: a registry that turns functions into JSON
Schema, a context object that carries authenticated dependencies past the model,
history serialization that keeps tool calls and their results paired. You know
what those parts cost.

Pydantic AI is a different answer to the same problem: **declare the types and let
the framework derive everything else**. This project is a short, self-contained
look at that ecosystem — what it does, what it buys you, and what it charges.

## 📌 When to Start

**Prerequisites:** Project 2 complete. You need the agent loop in your head, not
on screen — this project doesn't diff against it.

It is deliberately the **shortest** project in the roadmap, and it goes first for
that reason: one layer, one library, minimal infrastructure.

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

### Around those four

`UsageLimits` (a token and request ceiling per run) · tools that require approval
· message history you can serialize and reload · durable execution through
Temporal, DBOS or Prefect · OpenTelemetry-native instrumentation via Logfire.

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
        ├─ tools → PostgreSQL (orders, customers)
        ├─ requires_approval → DeferredToolRequests → you → resume
        └─ history ⇄ messages table (its representation)
```

## 📚 Tech Stack

- **pydantic-ai-slim[anthropic]** — the framework with only one provider
  installed. Plain `pydantic-ai` pulls every provider in existence.
- **`claude-haiku-4-5`** — small, fast, good at tool calling. The project is
  about types, not about model quality.
- **PostgreSQL** — orders, customers, and the serialized history
- **logfire** — optional, one afternoon: OpenTelemetry-native tracing that shows
  each turn, each tool call and each validation retry

## 🚀 Quick Start

```bash
uv sync
cp .env.example .env          # ANTHROPIC_API_KEY, DATABASE_URL
docker compose up -d --wait
uv run python -m app.seed     # a handful of fake customers and orders
uv run python -m app.triage "mi paquete nunca llegó y me cobraron dos veces"
```

## 🗺️ Phases

Five, each one small.

1. **One run, one type.** An `Agent` with `deps_type` and `output_type=Triage`.
   Print the derived JSON Schema for your tools and confirm `ctx` is absent from
   it — that absence is the whole dependency-injection idea, made visible.
2. **Tools with teeth.** `recent_orders` and `refund` against real rows. Make the
   model send an invalid amount on purpose and watch `ModelRetry` turn a failure
   into another turn.
3. **History.** Serialize a conversation, reload it in a fresh process, continue
   it. Open the stored JSON and look at what's actually in there. This is where
   you form an opinion about the trade above.
4. **Limits and approval.** `UsageLimits` to cap a run; `requires_approval=True`
   on `refund`, then the full `DeferredToolRequests` → approve/deny →
   `DeferredToolResults` → resume cycle, including a rejection.
5. **Instrument it.** Wire Logfire and re-run phase 4. Seeing a validation retry
   as a span is the fastest way to understand what the loop is really doing.

## 📊 What to record in APRENDIZAJES.md

| Question | Your answer |
|---|---|
| What's in the derived schema for each tool, and what isn't | |
| What happened when the model sent invalid arguments | |
| What the serialized history actually contains | |
| How a pause is represented, and where it lives | |
| Time to add a new tool | |
| Time to swap the model provider | |
| What you'd still have to build to run this in a worker | |

The last row is the honest one. Everything above it is what you were given.

## ⏱️ Timeline

5-6 hours. Short by design: one layer, almost no infrastructure, and every
problem it solves is a problem you've already met.

## ✅ Completion Checklist

- [ ] Two tools whose schema you printed and read
- [ ] `output_type` returning a validated object you write straight to the DB
- [ ] An invalid tool call recovered via `ModelRetry`
- [ ] A conversation that survives across processes
- [ ] A run stopped by `UsageLimits`
- [ ] A gated tool approved, and another one denied, both resumed
- [ ] Logfire showing the turns of a single run
- [ ] `APRENDIZAJES.md` with the table filled in

## 🎓 You're done when you can answer

- Why does `RunContext` keep `customer_id` out of the model's reach, and what
  would break if it were a plain argument?
- What is the difference between raising `ModelRetry` and raising anything else?
- What exactly is stored when you serialize the history, and what did you gain
  and lose by it not being the provider's blocks?
- A pause here is a return value. What does representing it that way make easy,
  and what does it make hard?
- Would you start a new agent on this? What would stop you?

See **[SOURCES.md](./SOURCES.md)** for official docs and related material.

---

**Made as part of Sr Backend Roadmap** 🚀

Start: after Project 2 · Duration: 5-6 h · Result: a working opinion about what
types buy you in an agent, before meeting the LangChain ecosystem
