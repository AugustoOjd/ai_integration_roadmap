"""A hand-written MCP client: JSON-RPC 2.0 over a subprocess's stdin/stdout.

No MCP library. The point is to see every byte the adapter will later hide.

    uv run python -m app.mcp_raw            # wire lines truncated
    uv run python -m app.mcp_raw --full     # wire lines complete

stdio framing (MCP spec, "Transports"): each message is one JSON object on one
line, UTF-8, terminated by \\n, no embedded newlines. Client writes to the
server's stdin, reads from its stdout; stderr is for logs and is not protocol.
"""

import argparse
import asyncio
import itertools
import json
import sys
from types import TracebackType
from typing import Any, Self

# The handshake-era revision. The SDK also knows "2026-07-28" (stateless, no
# initialize) — a different envelope, deliberately out of scope here.
PROTOCOL_VERSION = "2025-11-25"

# JSON-RPC's own error code for "I don't implement that method".
METHOD_NOT_FOUND = -32601


class MCPError(Exception):
    """A JSON-RPC error response: the *call* failed, not the tool."""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(f"[{code}] {message}")
        self.code, self.data = code, data


class RawMCPClient:
    """Launches a server command and speaks MCP to it over stdio."""

    def __init__(self, *command: str, full_wire: bool = False) -> None:
        self.command = command
        self.full_wire = full_wire
        self._ids = itertools.count(1)
        # Request id → Future the caller is awaiting. JSON-RPC responses can
        # arrive in any order; the id is the only thing that pairs them.
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._proc: asyncio.subprocess.Process | None = None
        self._reader: asyncio.Task[None] | None = None

    # ── lifecycle ────────────────────────────────────────────────────────────

    async def __aenter__(self) -> Self:
        self._proc = await asyncio.create_subprocess_exec(
            *self.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            # DEVNULL, not PIPE: a stderr pipe nobody reads fills its OS buffer
            # (~64 KiB) and the server blocks on its next log line — a
            # deadlock that looks like a hung tool call.
            stderr=asyncio.subprocess.DEVNULL,
            # StreamReader's default line limit is 64 KiB; one big tool result
            # is one line, and would raise LimitOverrunError.
            limit=1 << 20,
        )
        self._reader = asyncio.create_task(self._read_loop())
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        # The spec's stdio shutdown: close the server's stdin, wait for it to
        # exit, escalate to SIGTERM, then SIGKILL. There is no "shutdown" message.
        assert self._proc and self._proc.stdin and self._reader
        self._proc.stdin.close()
        try:
            await asyncio.wait_for(self._proc.wait(), timeout=2)
        except TimeoutError:
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=2)
            except TimeoutError:
                self._proc.kill()
                await self._proc.wait()
        self._reader.cancel()

    # ── wire ─────────────────────────────────────────────────────────────────

    def _show(self, arrow: str, line: str) -> None:
        if not self.full_wire and len(line) > 220:
            line = line[:220] + " …"
        print(f"{arrow} {line}")

    async def _send(self, message: dict[str, Any]) -> None:
        assert self._proc and self._proc.stdin
        # separators: compact JSON; ensure_ascii=False keeps "Bahía" readable.
        # json.dumps never emits a raw newline, so one message = one line.
        line = json.dumps(message, separators=(",", ":"), ensure_ascii=False)
        self._show("→", line)
        self._proc.stdin.write(line.encode() + b"\n")
        # drain() = backpressure: waits if the pipe buffer is full.
        await self._proc.stdin.drain()

    async def _read_loop(self) -> None:
        """Route every line from stdout. Runs for the client's whole life."""
        assert self._proc and self._proc.stdout
        try:
            async for raw in self._proc.stdout:  # yields one line at a time
                line = raw.decode().rstrip("\n")
                self._show("←", line)
                msg = json.loads(line)

                if "id" in msg and ("result" in msg or "error" in msg):
                    # A response to one of our requests.
                    fut = self._pending.pop(msg["id"], None)
                    if fut is None or fut.done():
                        continue  # late answer to a request we gave up on
                    if "error" in msg:
                        e = msg["error"]
                        fut.set_exception(MCPError(e["code"], e["message"], e.get("data")))
                    else:
                        fut.set_result(msg["result"])

                elif "id" in msg:
                    # A request *from the server* (ping, roots/list, sampling…).
                    # JSON-RPC requires an answer, or the server waits forever.
                    # We support none, so we say so explicitly.
                    await self._send({
                        "jsonrpc": "2.0", "id": msg["id"],
                        "error": {"code": METHOD_NOT_FOUND, "message": f"unsupported: {msg['method']}"},
                    })
                # else: a notification (no id). Nothing to answer; already printed.
        finally:
            # stdout closed = the server is gone. Anyone still waiting would
            # wait forever; fail them now with a clear cause. (Phase 6.)
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(ConnectionError("MCP server closed the connection"))
            self._pending.clear()

    async def request(self, method: str, params: dict[str, Any] | None = None, timeout: float = 10) -> Any:
        """Send a request and await its result. Raises MCPError on an error response."""
        req_id = next(self._ids)
        fut: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        # Registered *before* sending: the response can't beat us to the dict.
        self._pending[req_id] = fut
        message: dict[str, Any] = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params is not None:
            message["params"] = params
        await self._send(message)
        try:
            return await asyncio.wait_for(fut, timeout)
        except TimeoutError:
            self._pending.pop(req_id, None)
            # Tell the server we stopped waiting, so it can stop working.
            await self.notify("notifications/cancelled", {"requestId": req_id, "reason": "timeout"})
            raise

    async def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        """A notification: no id, so no response — fire and forget."""
        message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        await self._send(message)

    # ── MCP on top of JSON-RPC ───────────────────────────────────────────────

    async def initialize(self) -> dict[str, Any]:
        result = await self.request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            # What *we* support. Empty: no roots, no sampling, no elicitation —
            # so a well-behaved server won't send us those requests.
            "capabilities": {},
            "clientInfo": {"name": "nordix-raw-client", "version": "0.1.0"},
        })
        # The server may answer with a different version. If we don't speak
        # it, the spec says: disconnect.
        if result["protocolVersion"] != PROTOCOL_VERSION:
            raise MCPError(0, f"server wants protocol {result['protocolVersion']}")
        # Handshake step 3. Only after this may we send normal requests.
        await self.notify("notifications/initialized")
        return result

    async def list_tools(self) -> list[dict[str, Any]]:
        # Paginated in the spec (nextCursor). A two-tool server never pages,
        # but a real client would loop until nextCursor is absent.
        return (await self.request("tools/list"))["tools"]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        # Returns the raw result: content, isError, structuredContent. A tool
        # failure is NOT raised — it's a normal result with isError: true.
        return await self.request("tools/call", {"name": name, "arguments": arguments})


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true", help="don't truncate wire lines")
    args = parser.parse_args()

    # sys.executable: the same venv's Python, so the server finds fastmcp.
    async with RawMCPClient(sys.executable, "-m", "carrier.server", full_wire=args.full) as client:
        print("\n── 1. handshake")
        info = await client.initialize()
        print(f"   server: {info['serverInfo']}  capabilities: {list(info['capabilities'])}")

        print("\n── 2. discovery")
        for t in await client.list_tools():
            print(f"   {t['name']}: in={list(t['inputSchema'].get('properties', {}))}"
                  f" out={'outputSchema' in t} hints={t.get('annotations')}")

        print("\n── 3. a call that works")
        ok = await client.call_tool("track_shipment", {"tracking_code": "NX0000000019"})
        print(f"   isError={ok['isError']} status={ok['structuredContent']['status']}")

        print("\n── 4. a tool that refuses (protocol fine, tool said no)")
        bad = await client.call_tool("track_shipment", {"tracking_code": "NX9999999999"})
        print(f"   isError={bad['isError']} text={bad['content'][0]['text']!r}")

        print("\n── 5. an unknown tool — which layer fails is the server's choice")
        # The spec's example answers this with JSON-RPC error -32602; fastmcp
        # answers isError: true instead. A client must handle both.
        unknown = await client.call_tool("no_such_tool", {})
        print(f"   isError={unknown['isError']} text={unknown['content'][0]['text']!r}")

        print("\n── 6. an unknown method — always a protocol error")
        try:
            await client.request("tools/fly")
        except MCPError as e:
            print(f"   MCPError {e}")


if __name__ == "__main__":
    asyncio.run(main())
