"""What a run needs that the model must never choose."""

from dataclasses import dataclass

from app.db.pool import Pool


@dataclass(frozen=True)
class AgentContext:
    """Passed per run: `agent.ainvoke(..., context=AgentContext(...))`.

    Tools read it through `runtime.context`. It never appears in a tool's
    schema, so the model can't see it, fill it in, or lie about it — which is
    exactly why `customer_id` lives here and not as a tool argument. Who the
    caller is comes from authentication, not from the conversation.
    """

    pool: Pool
    customer_id: str
