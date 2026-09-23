"""Refuse remote tool calls about shipments that aren't the customer's."""

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from langchain.agents.middleware import AgentMiddleware, AgentState
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from app.core.context import AgentContext


class TrackingOwnershipMiddleware(AgentMiddleware[AgentState, AgentContext]):
    """wrap_tool_call: authorization for a tool whose body we can't edit.

    order_status authorizes inside its own SQL (WHERE customer_id = …). The
    carrier's track_shipment can't: it's someone else's code, and the carrier
    has no idea who Nordix's customers are. Any tracking code the model puts
    in the arguments — including one a customer typed from someone else's
    receipt — would be answered.

    So the check moves to the one place we still control: the boundary where
    our process is about to call theirs. The test for "tool or middleware?":
    if you own the tool's body, authorize there; if you don't, wrap it.
    """

    def __init__(self, guarded: Mapping[str, str]) -> None:
        """guarded: tool name → the argument holding a tracking code."""
        super().__init__()
        self.guarded = dict(guarded)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        call = request.tool_call
        arg = self.guarded.get(call["name"])
        if arg is None:
            # Not a guarded tool: pass through untouched.
            return await handler(request)

        code = str(call["args"].get(arg, "")).strip().upper()
        ctx: AgentContext = request.runtime.context

        async with ctx.pool.connection() as conn:
            cur = await conn.execute(
                "SELECT 1 FROM orders WHERE tracking_code = %s AND customer_id = %s",
                (code, ctx.customer_id),
            )
            owned = await cur.fetchone() is not None

        if not owned:
            # Short-circuit: handler() is never called, so the tracking code
            # never leaves our process. The ToolMessage must carry the same
            # tool_call_id — every tool_call needs its answer, or the next
            # model call is rejected by the provider.
            #
            # Same wording as the carrier's own "unknown code" error, on
            # purpose: "exists but isn't yours" must look exactly like
            # "doesn't exist", or the error itself leaks information.
            return ToolMessage(
                content=f"Unknown tracking code: {call['args'].get(arg)}",
                tool_call_id=call["id"],
                name=call["name"],
                status="error",
            )

        return await handler(request)
