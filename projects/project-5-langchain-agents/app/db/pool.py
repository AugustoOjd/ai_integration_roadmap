"""One async connection pool per process, opened and closed explicitly."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool

from app.core.config import settings

# The pool is generic over its connection type, and the connection over its row
# type. Spelling it out once lets every caller know rows are dicts, so
# `row["status"]` type-checks instead of looking like indexing a tuple by str.
Pool = AsyncConnectionPool[AsyncConnection[DictRow]]


# AsyncGenerator, not AsyncIterator: the decorator drives the generator with
# asend()/athrow() (athrow is how an exception in the `async with` body reaches
# the `yield`). AsyncIterator only promises __anext__, so typeshed deprecated it here.
@asynccontextmanager
async def open_pool() -> AsyncGenerator[Pool, None]:
    """Yield an open pool; close it on exit, even on error.

    `open=False` in the constructor is deliberate: opening an async pool in
    `__init__` is deprecated in psycopg_pool, because a constructor can't await.
    The `async with` opens it here, inside a running event loop.
    """
    # Rows come back as dicts: tools return them to the model as JSON, and
    # column names are what make that JSON readable.
    kwargs: dict[str, Any] = {"row_factory": dict_row}

    pool = Pool(
        conninfo=str(settings.DATABASE_URL),
        min_size=1,
        max_size=5,
        # row_factory in kwargs sets the behavior at runtime; connection_class
        # tells the type checker about it. psycopg can't infer one from the other.
        connection_class=AsyncConnection[DictRow],
        kwargs=kwargs,
        open=False,
    )
    async with pool:
        # Fail at startup, not on the agent's first tool call.
        await pool.wait(timeout=5)
        yield pool
