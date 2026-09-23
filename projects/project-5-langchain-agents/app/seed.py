"""Recreate the schema and load Nordix's customers and orders.

⚠️ Destructive: drops the tables first. Dev-only, run it as often as you like.

    uv run python -m app.seed
"""

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from app.db.pool import open_pool

SCHEMA = Path(__file__).parent / "db" / "schema.sql"

# Dates are relative to *now*: a hard-coded "delivered 2026-09-20" would drift
# out of the return window and silently change what the refund tests mean.
NOW = datetime.now(UTC)


def days_ago(n: int) -> datetime:
    return NOW - timedelta(days=n)


CUSTOMERS = [
    ("C-1001", "Lucía Fernández", "lucia@example.com"),
    ("C-1002", "Martín Gómez", "martin@example.com"),
    ("C-1003", "Sofía Ruiz", "sofia@example.com"),
]

# (id, customer, status, category, total, tracking_code, created_at, delivered_at)
# Each row is a scenario a later phase needs — the comment says which.
ORDERS = [
    # Happy path: delivered 3 days ago, well inside the 21-day window.
    ("A17", "C-1001", "delivered", "home", Decimal("38500.00"),
     "NX0000000017", days_ago(8), days_ago(3)),
    # Electronics delivered 14 days ago: past its 10-day window. Refund must be refused.
    ("A18", "C-1001", "delivered", "electronics", Decimal("215000.00"),
     "NX0000000018", days_ago(20), days_ago(14)),
    # Shipped, carrier has it in transit: the MCP tracking tool's case.
    ("A19", "C-1002", "shipped", "home", Decimal("12900.00"),
     "NX0000000019", days_ago(4), None),
    # Books delivered 40 days ago: past 21 but inside the 45-day books window.
    ("A20", "C-1002", "delivered", "books", Decimal("9800.00"),
     "NX0000000020", days_ago(45), days_ago(40)),
    # Shipped 12 days ago, no delivery: "lost" per ENV-011 §5 (>7 days stale).
    ("A21", "C-1003", "shipped", "electronics", Decimal("64000.00"),
     "NX0000000021", days_ago(12), None),
    # Still preparing: no tracking code yet (the CHECK allows NULL).
    ("A22", "C-1003", "preparing", "home", Decimal("5400.00"),
     None, days_ago(0), None),
    # Delivered and already refunded (see REFUNDS): phase 5's idempotency case.
    ("A23", "C-1001", "delivered", "home", Decimal("17300.00"),
     "NX0000000023", days_ago(10), days_ago(6)),
]

# (order_id, amount, reason, idempotency_key)
REFUNDS = [
    ("A23", Decimal("17300.00"), "damaged in transit", "refund:A23"),
]


async def main() -> None:
    async with open_pool() as pool, pool.connection() as conn:
        # One transaction for the whole seed: the connection context manager
        # commits on clean exit and rolls back on exception. Either the DB ends
        # up fully seeded or exactly as it was.
        async with conn.cursor() as cur:
            # A parameterless multi-statement string is fine for psycopg;
            # parameters are what force one statement per execute().
            await cur.execute(SCHEMA.read_text())

            # executemany: one prepared statement, many parameter tuples.
            # %s placeholders are bound server-side — never f-string SQL.
            await cur.executemany(
                "INSERT INTO customers (id, name, email) VALUES (%s, %s, %s)",
                CUSTOMERS,
            )
            await cur.executemany(
                """
                INSERT INTO orders (id, customer_id, status, category, total,
                                    tracking_code, created_at, delivered_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                ORDERS,
            )
            await cur.executemany(
                """
                INSERT INTO refunds (order_id, amount, reason, idempotency_key)
                VALUES (%s, %s, %s, %s)
                """,
                REFUNDS,
            )

    print(f"seeded {len(CUSTOMERS)} customers, {len(ORDERS)} orders, {len(REFUNDS)} refunds")


if __name__ == "__main__":
    asyncio.run(main())
