"""issue_refund — the one tool that moves money.

Everything here must hold with or without human approval (phase 5, step 2).
Approval stops the *model* from acting alone; it authorizes nothing. A tired
human approves twice, approves the wrong order, approves an expired return —
so the body validates as if nobody had looked.
"""

from decimal import Decimal
from typing import Annotated, Literal

from langchain.tools import ToolRuntime, tool
from pydantic import Field

from app.core.context import AgentContext
from app.tools.serialize import to_json

# DEV-004 §1: return window in days from delivery, by category.
RETURN_WINDOW_DAYS = {"electronics": 10, "books": 45}
DEFAULT_WINDOW_DAYS = 21

Reason = Literal["defective", "wrong_item", "damaged_in_transit", "changed_mind"]


@tool(parse_docstring=True)
async def issue_refund(
    order_id: str,
    reason: Reason,
    runtime: ToolRuntime[AgentContext],
    # Field constraints end up in the JSON schema the model sees (exclusiveMinimum,
    # decimal places) AND are enforced when the args are validated. Decimal,
    # not float: 0.1 + 0.2 != 0.3 is not a property you want in a refund.
    amount: Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)] | None = None,
) -> str:
    """Refund a delivered order, fully or partially. Moves money: only call it when the customer explicitly asks for a refund.

    Args:
        order_id: The order to refund, e.g. "A17".
        reason: Why the customer wants the refund.
        amount: Pesos to refund. Omit for a full refund of the order total.
    """
    ctx = runtime.context
    order_id = order_id.strip().upper()
    # One refund per order: the key is derived from *what* is being refunded,
    # never from the call (tool_call_id changes every time the model retries,
    # and a key that changes on retry protects nothing).
    key = f"refund:{order_id}"

    async with ctx.pool.connection() as conn, conn.transaction():
        # FOR UPDATE: lock the order row until commit. Two concurrent refunds of
        # the same order serialize here instead of both passing validation.
        cur = await conn.execute(
            """
            SELECT id, status, category, total, delivered_at,
                   -- The DB's clock, not ours: one source of time for policy.
                   now() - delivered_at AS since_delivery
            FROM orders
            WHERE id = %s AND customer_id = %s
            FOR UPDATE
            """,
            (order_id, ctx.customer_id),
        )
        order = await cur.fetchone()
        if order is None:
            return to_json({"error": "order_not_found", "order_id": order_id})

        # Idempotency first: a repeat of an already-issued refund must return
        # the same result, even if the window has closed since.
        cur = await conn.execute(
            "SELECT id, amount, reason, created_at FROM refunds WHERE idempotency_key = %s",
            (key,),
        )
        if (existing := await cur.fetchone()) is not None:
            return to_json({"status": "already_refunded", "order_id": order_id, "refund": existing})

        if order["status"] != "delivered":
            # A lost package (ENV-011 §5) is refundable too, but "lost" is the
            # carrier's fact, not ours — out of scope for this tool.
            return to_json({"error": "not_delivered", "order_id": order_id, "status": order["status"]})

        window = RETURN_WINDOW_DAYS.get(order["category"], DEFAULT_WINDOW_DAYS)
        days = order["since_delivery"].days
        if days > window:
            return to_json({
                "error": "return_window_expired", "order_id": order_id,
                "category": order["category"], "window_days": window, "days_since_delivery": days,
            })

        refund_amount = order["total"] if amount is None else amount
        if refund_amount > order["total"]:
            return to_json({
                "error": "amount_exceeds_total", "order_id": order_id,
                "requested": refund_amount, "total": order["total"],
            })

        cur = await conn.execute(
            """
            INSERT INTO refunds (order_id, amount, reason, idempotency_key)
            VALUES (%s, %s, %s, %s)
            -- Belt and braces: the lock above serializes normal traffic; the
            -- UNIQUE catches anything that gets past it. No exception, no row.
            ON CONFLICT (idempotency_key) DO NOTHING
            RETURNING id, amount, created_at
            """,
            (order_id, refund_amount, reason, key),
        )
        created = await cur.fetchone()
        # Commit happens when the `transaction()` block exits cleanly.

    if created is None:
        return to_json({"status": "already_refunded", "order_id": order_id})
    return to_json({"status": "refunded", "order_id": order_id, "refund": created})
