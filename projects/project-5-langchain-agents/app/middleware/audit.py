"""Record every model decision in Postgres. Observes; never changes the run."""

from typing import Any

from langchain.agents.middleware import AgentMiddleware, AgentState
from langchain_core.messages import AIMessage
from langgraph.config import get_config
from langgraph.runtime import Runtime
from psycopg.types.json import Jsonb

from app.core.context import AgentContext


# Pinned to AgentContext, unlike BudgetMiddleware: an audit row must say *who*,
# and "who" is this app's context. Cross-cutting doesn't mean context-free.
class AuditMiddleware(AgentMiddleware[AgentState, AgentContext]):
    """Node-style hook: after_model runs as its own graph node, after `model`.

    Compare with BudgetMiddleware's wrap hook:
    - It can't stop or alter the call — the call already happened. It sees
      the *result*, as state.
    - It writes state by returning a dict (here: None, it only observes).
    - It also sees what the wrap hooks produced: BudgetMiddleware's refusal
      lands in state as an AIMessage too, so it gets audited like any other.
    """

    async def aafter_model(
        self, state: AgentState, runtime: Runtime[AgentContext]
    ) -> dict[str, Any] | None:
        # The model node just appended its AIMessage; it's the last message.
        msg = state["messages"][-1]
        if not isinstance(msg, AIMessage):
            return None

        if msg.response_metadata.get("budget_exceeded"):
            decision = "budget_exceeded"
        elif msg.tool_calls:
            decision = "tool_calls"
        else:
            decision = "final"

        usage = msg.usage_metadata or {}
        # thread_id isn't on Runtime; it's in the run's config, which LangGraph
        # exposes to any code running inside a node through a contextvar.
        thread_id = get_config().get("configurable", {}).get("thread_id")
        ctx = runtime.context

        # Fail closed: if the insert raises, the run fails. An agent that
        # keeps acting while its audit trail is down is acting unobserved —
        # and in phase 5 some of these actions move money. The opposite
        # choice (log and continue) is legitimate for a read-only bot; it's a
        # decision, not a default.
        async with ctx.pool.connection() as conn:
            await conn.execute(
                """
                INSERT INTO model_audit (customer_id, thread_id, decision, tool_calls,
                                         input_tokens, output_tokens, model)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    ctx.customer_id,
                    thread_id,
                    decision,
                    # Jsonb wraps the value so psycopg sends it as jsonb, not text.
                    # Only name + args: the call id is LangChain bookkeeping.
                    Jsonb([{"name": c["name"], "args": c["args"]} for c in msg.tool_calls]),
                    usage.get("input_tokens"),
                    usage.get("output_tokens"),
                    msg.response_metadata.get("model_name"),
                ),
            )

        # None = no state update. Returning {"jump_to": "end"} here could end
        # the run — but only *after* the call was made and paid for.
        return None
