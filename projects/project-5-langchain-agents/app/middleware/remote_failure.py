"""Turn a failing remote tool into a tool error the model can work around."""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

import anyio
from langchain.agents.middleware import AgentMiddleware, AgentState
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command
from mcp.shared.exceptions import MCPError

from app.core.context import AgentContext

logger = logging.getLogger(__name__)

# What a broken *transport* looks like from here. Observed in phase 6: a dead
# server raises MCPError("Connection closed") instantly, on every later call,
# forever — the adapter doesn't reconnect. The rest are the lower layers
# (pipes, anyio streams) failing before MCP can name the problem.
TRANSPORT_ERRORS: tuple[type[BaseException], ...] = (
    MCPError,
    TimeoutError,
    OSError,  # includes ConnectionError, BrokenPipeError
    anyio.ClosedResourceError,
    anyio.BrokenResourceError,
)


class RemoteToolFailureMiddleware(AgentMiddleware[AgentState, AgentContext]):
    """wrap_tool_call around remote tools only: bound the wait, contain the failure.

    The adapter's position is that a transport failure isn't the model's
    problem, so it raises — and one raised exception ends the whole run. For
    a support chat that's the wrong trade: the carrier being down shouldn't
    stop the agent from answering what Nordix's own data can answer.

    Scoped by name to remote tools on purpose. A local tool raising is a bug
    in *our* code; swallowing it would turn a crash you'd fix into an agent
    that politely lies around it.
    """

    def __init__(self, remote_tool_names: Iterable[str], timeout_s: float) -> None:
        super().__init__()
        self.remote = frozenset(remote_tool_names)
        self.timeout_s = timeout_s

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        call = request.tool_call
        if call["name"] not in self.remote:
            return await handler(request)

        try:
            # The adapter puts no timeout on a tool call; a server that is
            # alive but silent would hold the run (and the customer) forever.
            # asyncio.timeout cancels the pending call; the MCP client sends
            # notifications/cancelled for it — the same message your raw
            # client sent on timeout.
            async with asyncio.timeout(self.timeout_s):
                return await handler(request)
        except TRANSPORT_ERRORS as e:
            # Full detail for us, in the log; nothing internal for the model,
            # which would happily repeat "MCPError -32000" to a customer.
            logger.warning("remote tool %s failed: %r", call["name"], e, exc_info=True)
            return ToolMessage(
                content=(
                    "The carrier's tracking service is unavailable right now. "
                    "Answer from order data only, and tell the customer live "
                    "tracking can't be checked at the moment."
                ),
                tool_call_id=call["id"],
                name=call["name"],
                status="error",
            )
