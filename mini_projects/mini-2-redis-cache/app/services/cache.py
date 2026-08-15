import logging

import redis.asyncio as redis

from app.config import settings

logger = logging.getLogger(__name__)

# Like the SQLAlchemy engine in database.py, this manages its own connection
# pool lazily — building the client here doesn't open a socket yet, that only
# happens on the first actual command.
# decode_responses=True: get() returns str instead of bytes, matching what we
# store (JSON text), so callers never have to .decode() the result by hand.
redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)

# Key naming follows the pattern documented in README.md's "Redis Keys Pattern"
NOTES_LIST_KEY = "notes:all"
NOTE_KEY_PREFIX = "note:"
DEFAULT_TTL_SECONDS = 3600  # 1 hour


def _note_key(note_id: str) -> str:
    return f"{NOTE_KEY_PREFIX}{note_id}"


async def _get_str(key: str) -> str | None:
    """redis-py's stubs type get() as `bytes | str | None` no matter what
    decode_responses was set to — there's no generic parameter to narrow it
    from the outside in this version. isinstance() narrows it for real here,
    which is safe: decode_responses=True guarantees str at runtime."""
    value = await redis_client.get(key)
    if value is None or isinstance(value, str):
        return value

    # Only reachable if decode_responses got turned off: every read would then
    # silently look like a cache miss and the cache would refill forever without
    # a single hit. Log loudly instead of hiding it behind a plain `return None`.
    logger.warning(
        "Redis returned %s for %r, expected str — is decode_responses=True still set?",
        type(value).__name__,
        key,
    )
    return None


async def get_notes_list() -> str | None:
    """Cached JSON array of all notes, or None on a cache miss."""
    return await _get_str(NOTES_LIST_KEY)


async def set_notes_list(payload: str, ttl: int = DEFAULT_TTL_SECONDS) -> None:
    await redis_client.set(NOTES_LIST_KEY, payload, ex=ttl)


async def get_note(note_id: str) -> str | None:
    """Cached JSON object for a single note, or None on a cache miss."""
    return await _get_str(_note_key(note_id))


async def set_note(note_id: str, payload: str, ttl: int = DEFAULT_TTL_SECONDS) -> None:
    await redis_client.set(_note_key(note_id), payload, ex=ttl)


async def invalidate(note_id: str | None = None) -> None:
    """Call this after every write (create/update/delete). The list is stale
    after ANY write, so it's always dropped; note_id is only passed when a
    specific note's own cache entry also needs to go (update/delete)."""
    keys = [NOTES_LIST_KEY]
    if note_id is not None:
        keys.append(_note_key(note_id))
    await redis_client.delete(*keys)
