import json

import pytest
from httpx import AsyncClient

from app.services import cache

# A note that exists ONLY in Redis, never in Postgres. If an endpoint returns it,
# the response provably came from the cache and not from a database query.
GHOST_TITLE = "Only in cache"
GHOST_NOTE = {
    "id": "11111111-1111-1111-1111-111111111111",
    "title": GHOST_TITLE,
    "content": "Never inserted into Postgres",
    "created_at": "2026-01-01T00:00:00+00:00",
}


async def test_list_cache_miss_then_hit(client: AsyncClient):
    """MISS fills the cache (with a TTL), and the next read is served from it."""
    await client.post("/notes/", json={"title": "A", "content": "a"})

    # MISS: nothing cached yet (conftest flushes Redis before every test)
    assert await cache.get_notes_list() is None
    assert (await client.get("/notes/")).status_code == 200
    assert await cache.get_notes_list() is not None

    # TTL > 0 proves an expiry was set; -1 would mean the key never expires
    assert 0 < await cache.redis_client.ttl(cache.NOTES_LIST_KEY) <= cache.DEFAULT_TTL_SECONDS

    # HIT: overwrite the cached copy with data Postgres doesn't have. Getting it
    # back means the endpoint read Redis instead of querying the database.
    await cache.set_notes_list(json.dumps([GHOST_NOTE]))
    assert [n["title"] for n in (await client.get("/notes/")).json()] == [GHOST_TITLE]


async def test_single_note_cache_miss_then_hit(client: AsyncClient):
    """Same cycle as above, for the per-note `note:{id}` key."""
    note_id = (await client.post("/notes/", json={"title": "Cached", "content": "v1"})).json()["id"]

    assert await cache.get_note(note_id) is None
    assert (await client.get(f"/notes/{note_id}")).json()["title"] == "Cached"
    assert await cache.get_note(note_id) is not None

    await cache.set_note(note_id, json.dumps({**GHOST_NOTE, "id": note_id}))
    assert (await client.get(f"/notes/{note_id}")).json()["title"] == GHOST_TITLE


async def test_create_invalidates_list_cache(client: AsyncClient):
    """A new note makes the cached list stale — but there's no per-note key yet."""
    await client.get("/notes/")
    assert await cache.get_notes_list() is not None

    await client.post("/notes/", json={"title": "New", "content": "n"})

    assert await cache.get_notes_list() is None


# Both writes must drop the list AND that note's own entry, so they assert the
# same thing — parametrize runs this body once per HTTP method instead of
# duplicating it. Without these, a stale note would keep being served with a
# 200 OK until its TTL expired an hour later: no error, just wrong data.
@pytest.mark.parametrize("method", ["put", "delete"])
async def test_write_invalidates_list_and_note_caches(client: AsyncClient, method: str):
    note_id = (await client.post("/notes/", json={"title": "Before", "content": "v1"})).json()["id"]

    await client.get("/notes/")  # populate list cache
    await client.get(f"/notes/{note_id}")  # populate single-note cache
    assert await cache.get_notes_list() is not None
    assert await cache.get_note(note_id) is not None

    if method == "put":
        await client.put(f"/notes/{note_id}", json={"title": "After", "content": "v2"})
    else:
        await client.delete(f"/notes/{note_id}")

    assert await cache.get_notes_list() is None
    assert await cache.get_note(note_id) is None


async def test_unchanged_content_returns_304(client: AsyncClient):
    """Client-side caching: same ETag back means "you already have this"."""
    await client.post("/notes/", json={"title": "A", "content": "a"})

    first = await client.get("/notes/")
    assert first.status_code == 200
    etag = first.headers["etag"]

    second = await client.get("/notes/", headers={"If-None-Match": etag})

    assert second.status_code == 304
    assert second.content == b""  # the whole point: no body over the wire


async def test_etag_stops_matching_after_a_write(client: AsyncClient):
    """A stale ETag must NOT produce a 304, or clients would keep showing old data."""
    etag = (await client.get("/notes/")).headers["etag"]

    await client.post("/notes/", json={"title": "New", "content": "n"})

    response = await client.get("/notes/", headers={"If-None-Match": etag})
    assert response.status_code == 200
    assert len(response.json()) == 1
