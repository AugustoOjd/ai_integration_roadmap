"""The carrier's tools, discovered over MCP instead of imported.

Compare with app/mcp_raw.py: same server, same wire — the adapter does the
handshake, the id bookkeeping and the error routing you wrote by hand.
"""

import sys
import warnings
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastmcp.client.transports import StdioTransport
from langchain_core._api import LangChainBetaWarning
from langchain_core.tools import BaseTool

from app.core.config import ROOT

# langchain.mcp warns once per process that it's beta. We chose it knowing
# that (see PHASES.md); the warning would only add noise to every chat.
# Scoped to this one import, so no other beta warning gets hidden.
with warnings.catch_warnings():
    warnings.simplefilter("ignore", LangChainBetaWarning)
    from langchain.mcp import MCPAdapter


LOG_FILE = ROOT / "logs" / "carrier.log"


def _transport() -> StdioTransport:
    LOG_FILE.parent.mkdir(exist_ok=True)
    # An explicit transport, not a bare string: MCPAdapter refuses a str that
    # isn't an http(s) URL, precisely so a config value can't silently turn
    # into "launch this file as a subprocess".
    return StdioTransport(
        # Same command app/mcp_raw.py runs. sys.executable → this venv's Python.
        command=sys.executable,
        args=["-m", "carrier.server"],
        cwd=str(ROOT),
        # env=None doesn't mean "inherit everything": the MCP SDK passes only a
        # safe default set (PATH, HOME…). Our ANTHROPIC_API_KEY never reaches
        # the carrier's process — and a service you don't own shouldn't see it.
        #
        # The server's stderr (its logs) goes to a file. The default is our
        # stderr, which would interleave its log lines with the chat. Not
        # DEVNULL either: when the carrier misbehaves (phase 6), this file is
        # the only view into the other process.
        log_file=LOG_FILE,
    )


@asynccontextmanager
async def carrier_tools() -> AsyncGenerator[list[BaseTool], None]:
    """Yield the carrier's tools, with the connection held open until exit.

    Why hold it: each adapted tool runs `async with client:` on every call.
    With a connection already open that's a no-op; without one, every tool
    call would open a fresh session and redo the whole initialize handshake.
    """
    async with MCPAdapter(_transport()) as adapter:
        # tools/list happens here, at runtime. The agent's tool set is now
        # whatever this server says it is today — discovery, not import.
        yield await adapter.list_tools()
