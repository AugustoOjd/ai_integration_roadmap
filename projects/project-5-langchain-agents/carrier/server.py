"""Rápido Sur — the carrier's tracking service, exposed over MCP (stdio).

Plays the part of a system Nordix does NOT own: separate process, its own
data, no access to our Postgres, and no import from `app`. Everything the
agent learns from it crosses a process boundary as JSON-RPC.

    uv run python -m carrier.server      # speaks MCP on stdin/stdout

Don't run it by hand and type at it — a client launches it as a subprocess.
"""

from datetime import UTC, datetime, timedelta
from typing import Literal

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import BaseModel

# The name travels in the `initialize` response as serverInfo.name.
mcp = FastMCP("rapido-sur-tracking")

Status = Literal[
    "dispatched", "in_transit", "out_for_delivery", "delivered",
    "failed_visit", "returned_to_origin",
]


class TrackingEvent(BaseModel):
    at: datetime
    status: Status
    location: str


class Shipment(BaseModel):
    tracking_code: str
    status: Status
    last_update: datetime
    # ENV-011 §5: no update for more than 7 days = lost. The carrier computes
    # it; the agent just reads it. Business rules live with whoever owns the data.
    stale: bool
    events: list[TrackingEvent]


# ── The carrier's own data ───────────────────────────────────────────────────
# In-memory and relative to process start, mirroring app/seed.py's dates.
# The tracking codes are the only thing shared with Nordix — as in real life.
_NOW = datetime.now(UTC)


def _ago(days: float) -> datetime:
    return _NOW - timedelta(days=days)


def _events(*rows: tuple[float, Status, str]) -> list[TrackingEvent]:
    return [TrackingEvent(at=_ago(d), status=s, location=loc) for d, s, loc in rows]


_SHIPMENTS: dict[str, list[TrackingEvent]] = {
    "NX0000000017": _events((7, "dispatched", "CABA"), (5, "in_transit", "CABA"),
                            (3.2, "out_for_delivery", "Palermo"), (3, "delivered", "Palermo")),
    "NX0000000018": _events((19, "dispatched", "CABA"), (16, "in_transit", "Rosario"),
                            (14, "delivered", "Rosario")),
    # A19: moving, not delivered yet — the normal "where is it?" case.
    "NX0000000019": _events((3, "dispatched", "CABA"), (2, "in_transit", "Córdoba")),
    "NX0000000020": _events((43, "dispatched", "CABA"), (40, "delivered", "La Plata")),
    # A21: last scan 9 days ago → stale → lost per ENV-011 §5.
    "NX0000000021": _events((11, "dispatched", "CABA"), (9, "in_transit", "Bahía Blanca")),
    "NX0000000023": _events((9, "dispatched", "CABA"), (7, "failed_visit", "Quilmes"),
                            (6, "delivered", "Quilmes")),
}

_STALE_AFTER = timedelta(days=7)


# ── Tools ────────────────────────────────────────────────────────────────────
# Same idea as LangChain's @tool: signature + docstring → JSON schema. One
# difference to look for on the wire: the return annotation becomes an
# `outputSchema`. LangChain's tool schema told the model nothing about results.
@mcp.tool(
    # Hints, not guarantees: a client may use them (e.g. skip confirmation for
    # read-only tools) but must not trust them from a server it doesn't trust.
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
)
def track_shipment(tracking_code: str) -> Shipment:
    """Current status and full scan history of a Rápido Sur shipment.

    Args:
        tracking_code: "NX" followed by 10 digits, e.g. "NX0000000019".
    """
    events = _SHIPMENTS.get(tracking_code.strip().upper())
    if events is None:
        # ToolError → a *successful* JSON-RPC response whose result has
        # isError: true. The protocol worked; the tool refused. The model sees
        # the message and can react. A JSON-RPC error means the call itself
        # was malformed — different layer, different audience.
        raise ToolError(f"Unknown tracking code: {tracking_code}")

    last = events[-1]
    return Shipment(
        tracking_code=tracking_code,
        status=last.status,
        last_update=last.at,
        stale=last.status != "delivered" and _NOW - last.at > _STALE_AFTER,
        events=events,
    )


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
def carrier_contact() -> dict[str, str]:
    """How the customer can reach Rápido Sur directly (claims, pickup points)."""
    return {"phone": "0800-555-7878", "claims_url": "https://rapidosur.example/reclamos"}


if __name__ == "__main__":
    # stdio: stdout IS the protocol channel. A stray print() here would put
    # non-JSON on the wire and break the client — hence no banner.
    mcp.run(transport="stdio", show_banner=False)
