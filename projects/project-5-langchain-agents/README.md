# 🛠️ PROJECT 5: LangChain Agents

**The loop, as a building block — and the six places you can get inside it.**

Project 4 was a chain: input goes in, output comes out, nothing decides anything.
This one adds the decision. `create_agent` gives you the loop you once wrote by
hand — model, tools, repeat — as one call. The project is about what that costs
and, more interestingly, what they gave you in exchange for the control you lost.

The exchange has a name: **middleware**. It is the most transferable idea in the
whole LangChain ecosystem and the reason this project exists.

## 📌 When to Start

**Prerequisites:** Project 4, and an agent loop you've written yourself. You need
to know what `while the model keeps asking for tools` feels like from the inside.

```
P4  LangChain Core                   LCEL, Runnable, retrieval
P5  LangChain Agents  ← estás aquí   create_agent, tools, MCP, middleware
P6  LangGraph                        estado durable, interrupt
P7  Deep Agents                      harness, tareas largas
P8  Agent Ops                        evals, monitoring, deploy
```

Everything here runs **inside one request**. The agent decides, tools run, an
answer comes back — and when the process dies, the run dies with it. Making a run
outlive its process is Project 6.

## 🎯 The Core

### 1. `create_agent` — the loop you already know

```python
from langchain.agents import create_agent
from langchain.tools import tool

@tool
def order_status(order_id: str) -> str:
    """Look up the current status of an order by its id."""
    return db.status(order_id)

# model, tools, prompt. The while-loop is inside.
agent = create_agent(
    model="anthropic:claude-haiku-4-5",
    tools=[order_status],
    system_prompt="You handle support tickets. Never invent an order id.",
)

result = agent.invoke({"messages": [{"role": "user", "content": "where is #A17?"}]})
```

That's the whole thing. `@tool` derives the schema from the signature and the
docstring; `create_agent` runs model → tools → model until the model stops asking.

Note what it returns: a **graph**, not an object with a `.run()`. `create_agent`
is built on LangGraph — which is why Project 6 is the next step and not a detour.

### 2. Memory is a checkpointer plus a `thread_id`

```python
from langgraph.checkpoint.memory import InMemorySaver

agent = create_agent(..., checkpointer=InMemorySaver())

# The thread id is the conversation. Same id, same history, automatically.
config = {"configurable": {"thread_id": "ticket-4471"}}
agent.invoke({"messages": [...]}, config=config)
agent.invoke({"messages": [...]}, config=config)   # remembers the first turn
```

You wrote this by hand once: load the history, append, save. Here it's a
constructor argument. Keep the seam in view — `InMemorySaver` is a toy, and
swapping it for a durable one is most of Project 6.

### 3. Middleware — six hooks into a loop you don't own

This is the idea worth the whole project. A framework that hands you a closed
loop has to give you a way back in, and this is it:

| Hook | Runs |
|---|---|
| `before_agent` | once, before the run starts |
| `before_model` | before every model call |
| `wrap_model_call` | **around** every model call |
| `after_model` | after every model response |
| `wrap_tool_call` | **around** every tool call |
| `after_agent` | once, when the run ends |

```python
from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse

class BudgetMiddleware(AgentMiddleware):
    """Stop a run that has spent too much. The agent never knows this exists."""

    def wrap_model_call(self, request: ModelRequest, handler) -> ModelResponse:
        # `handler` is the real call. Wrapping it means you own both sides:
        # what goes to the model, and what comes back.
        if self.spent > self.ceiling:
            raise BudgetExceeded(self.spent)
        response = handler(request)
        self.spent += response.usage.total_tokens
        return response

agent = create_agent(..., middleware=[BudgetMiddleware()])
```

You already know this pattern from FastAPI. The move worth internalizing is
recognizing it here: **cross-cutting concerns don't belong in the loop**, and the
loop isn't yours anyway. Budget, retries, redaction, rate limits, audit logging —
all of it is middleware, and all of it survives an upgrade of the loop.

The library ships several ready-made: `SummarizationMiddleware`,
`HumanInTheLoopMiddleware`, plus tool retry, model fallback, rate limiting and PII
detection. Read their source. They are the best documentation of the hooks.

### 4. MCP — tools stop being functions in your process

Every tool so far is a Python function you import. MCP asks the other question:
**what if the tools are a service you don't own?**

```python
from langchain.mcp import MCPAdapter

# The adapter infers the transport from what you hand it:
# a URL → HTTP, a Path → launches the script over stdio.
async with MCPAdapter("https://tools.internal/mcp") as adapter:
    tools = await adapter.list_tools()
    agent = create_agent("anthropic:claude-haiku-4-5", tools)
```

For a backend engineer this is the most valuable topic in the project, and it has
nothing to do with LLMs: it's a protocol question. Discovery, transport, auth,
versioning, what happens when half the tools are unreachable. A tool that crosses
a network boundary is a dependency, with everything that implies.

Which is why **Phase 4 makes you write the server by hand first**, against the
spec, before touching the adapter. Same rule as always: the protocol before the
client.

### 5. Human-in-the-loop as middleware

`refund` shouldn't fire because a model felt like it. `HumanInTheLoopMiddleware`
interrupts before a configured tool runs and waits for a decision — approve,
reject, or edit the arguments.

Note where it lives: it's *middleware*, not a feature of the loop. That's the
whole design philosophy in one example. And note what it needs to work at all —
somewhere to store the paused run. That requirement is Project 6 knocking.

## 🛑 What stays yours

| Still yours | Why |
|---|---|
| **The process boundary** | The agent runs in *your* process. A queue, a worker, a timeout — invisible to it. |
| **Durable state** | `InMemorySaver` dies with the process. A pause that survives a deploy is Project 6. |
| **Idempotency** | Nothing knows that `issue_refund` moves money. Run it twice, refund twice. |
| **Which tool is sensitive** | HITL takes a list of tool names. Deciding what goes on that list is a business decision. |
| **Authorization inside the tool** | Approval stops the *model* from acting alone. It authorizes nothing. The tool body still runs. |
| **What happens when the MCP server is down** | Your problem, and a normal one: it's a network dependency like any other. |

## 🏗️ Architecture

```
CLI/HTTP → create_agent(model, tools, middleware=[...])
              ├─ middleware  budget · audit · HITL
              ├─ tools       local  → PostgreSQL (orders, customers)
              │              remote → MCP server (your own, phase 4)
              └─ checkpointer (in-memory: dies with the process)
```

## 📚 Tech Stack

- **langchain** — `create_agent`, `@tool`, `langchain.agents.middleware`
- **langchain[mcp]** — `MCPAdapter`. En beta, requiere `>=1.4.0`
- **langchain-anthropic** — `claude-haiku-4-5`: rápido y bueno llamando tools
- **mcp** — el SDK del protocolo, para escribir el servidor de la Fase 4
- **PostgreSQL** — pedidos y clientes
- **LangSmith** — opcional. Un agente con middleware tiene muchas capas; verlas
  como trazas es la diferencia entre depurar y adivinar

## 🚀 Quick Start

```bash
uv sync
cp .env.example .env          # ANTHROPIC_API_KEY, DATABASE_URL
docker compose up -d --wait
uv run python -m app.seed
uv run python -m app.chat "¿dónde está mi pedido A17?"
```

## 🗺️ Phases

1. **The loop in one call.** `create_agent` with two read-only tools. Print the
   schema the model sees and confirm it matches your signatures.
2. **Memory.** Add `InMemorySaver` and a `thread_id`. Hold a three-turn
   conversation, then restart the process and watch it forget. That amnesia is
   the argument for Project 6.
3. **Your first middleware.** Write `BudgetMiddleware` with `wrap_model_call`.
   Then an audit middleware with `after_model`. Neither touches the agent.
4. **MCP, protocol first.** Write an MCP server by hand exposing two tools, drive
   it with raw protocol messages and read what goes over the wire. *Then* connect
   `MCPAdapter` and delete the hand-rolled client.
5. **Approval.** `HumanInTheLoopMiddleware` on `issue_refund`. Approve one, reject
   one, edit the arguments of a third.
6. **Break it.** Kill the MCP server mid-run. Exceed the budget mid-run. Decide
   what each failure should look like to whoever asked the question.

## 📊 What to record in APRENDIZAJES.md

| Question | Your answer |
|---|---|
| What the derived tool schema contains, and what it omits | |
| Which of your hand-written loop's concerns became middleware | |
| Which hook you reached for, and why that one | |
| What the raw MCP exchange looks like before any client | |
| Where a paused run lives, and what kills it | |
| What broke when the MCP server went away | |

## ⏱️ Timeline

8-10 hours. The loop takes an afternoon; middleware and MCP take the rest, and
they're the parts worth the time.

## ✅ Completion Checklist

- [ ] Agent answering with two local tools
- [ ] Multi-turn conversation over a `thread_id`
- [ ] Two custom middleware, one wrap-style and one node-style
- [ ] MCP server written by hand, exercised over the raw protocol
- [ ] The same server consumed through `MCPAdapter`
- [ ] A refund approved, one rejected, one edited
- [ ] `APRENDIZAJES.md` with the table filled in

## 🎓 You're done when you can answer

- `create_agent` returns a graph. What follows from that, and why is Project 6 the
  next step rather than an optional extra?
- When do you reach for `wrap_model_call` instead of `before_model`?
- Which concerns belong in middleware and which belong in a tool? What's the test?
- What did you learn from the raw MCP messages that the adapter hides?
- Approval is middleware, not a loop feature. What does that buy, and what does it
  fail to protect against?

See **[SOURCES.md](./SOURCES.md)** for official docs and related material.

---

**Made as part of Sr Backend Roadmap** 🚀

Duration: 8-10 h · Result: a loop you don't own, and six documented ways to get
back inside it
