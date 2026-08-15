import hashlib
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.note import Note
from app.schemas.note import NoteCreate, NoteResponse, NoteUpdate
from app.services import cache

# __name__ is "app.routes.notes", so log lines are tagged with their source.
# Level/format are configured once in main.py.
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notes", tags=["notes"])

# Validates/serializes a list[NoteResponse] to and from a single JSON string —
# used for the "notes:all" cache entry, which stores the whole list as one value
notes_list_adapter = TypeAdapter(list[NoteResponse])


def _json_or_304(request: Request, payload: str) -> Response:
    """Return the JSON payload, or 304 Not Modified if the client already has it.

    This is the second, client-side caching layer: Redis saves us a Postgres
    query, an ETag saves us sending the body over the network at all.

    The ETag is a fingerprint of the exact bytes we would send. The client
    stores it, echoes it back in If-None-Match, and an unchanged fingerprint
    means its copy is still good. Any write changes the payload, which changes
    the hash, so staleness can't go unnoticed.

    md5 is fine here: this identifies content, it isn't a security boundary.
    """
    etag = f'"{hashlib.md5(payload.encode()).hexdigest()}"'  # quotes required by HTTP spec

    if request.headers.get("if-none-match") == etag:
        # 304 must carry the ETag and no body — the client reuses what it has
        logger.info("NOT MODIFIED -> 304 (client copy still valid, body not sent)")
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})

    return Response(content=payload, media_type="application/json", headers={"ETag": etag})


@router.get("/", response_model=list[NoteResponse])
async def list_notes(request: Request, db: AsyncSession = Depends(get_db)):
    payload = await cache.get_notes_list()

    if payload is not None:
        # Cache HIT: Postgres never gets touched for this request
        logger.info("CACHE HIT  -> %s (served from Redis)", cache.NOTES_LIST_KEY)
    else:
        logger.info("CACHE MISS -> %s (querying Postgres)", cache.NOTES_LIST_KEY)
        result = await db.execute(select(Note).order_by(Note.created_at.desc()))
        notes = result.scalars().all()

        # Serialize once: the same string is both cached and sent to the client
        payload = notes_list_adapter.dump_json(notes_list_adapter.validate_python(notes)).decode()
        await cache.set_notes_list(payload)
        logger.info(
            "CACHE FILL -> %s (%d notes, ttl=%ds)",
            cache.NOTES_LIST_KEY,
            len(notes),
            cache.DEFAULT_TTL_SECONDS,
        )

    return _json_or_304(request, payload)


@router.post("/", response_model=NoteResponse, status_code=status.HTTP_201_CREATED)
async def create_note(note_in: NoteCreate, db: AsyncSession = Depends(get_db)):
    note = Note(title=note_in.title, content=note_in.content)
    db.add(note)
    await db.commit()
    await db.refresh(note)

    # The cached list no longer includes this note — drop it
    await cache.invalidate()
    logger.info("CACHE DROP -> %s (note created)", cache.NOTES_LIST_KEY)
    return note


@router.get("/{note_id}", response_model=NoteResponse)
async def get_note(note_id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_db)):
    key = f"{cache.NOTE_KEY_PREFIX}{note_id}"
    payload = await cache.get_note(str(note_id))

    if payload is not None:
        logger.info("CACHE HIT  -> %s (served from Redis)", key)
    else:
        logger.info("CACHE MISS -> %s (querying Postgres)", key)
        note = await db.get(Note, note_id)
        if note is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")

        payload = NoteResponse.model_validate(note).model_dump_json()
        await cache.set_note(str(note_id), payload)
        logger.info("CACHE FILL -> %s (ttl=%ds)", key, cache.DEFAULT_TTL_SECONDS)

    return _json_or_304(request, payload)


@router.put("/{note_id}", response_model=NoteResponse)
async def update_note(note_id: uuid.UUID, note_in: NoteUpdate, db: AsyncSession = Depends(get_db)):
    note = await db.get(Note, note_id)
    if note is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")

    note.title = note_in.title
    note.content = note_in.content
    await db.commit()
    await db.refresh(note)

    # Both the stale list and this note's own cached copy need to go
    await cache.invalidate(note_id=str(note_id))
    logger.info(
        "CACHE DROP -> %s + %s%s (note updated)",
        cache.NOTES_LIST_KEY,
        cache.NOTE_KEY_PREFIX,
        note_id,
    )
    return note


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_note(note_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    note = await db.get(Note, note_id)
    if note is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")

    await db.delete(note)
    await db.commit()
    await cache.invalidate(note_id=str(note_id))
    logger.info(
        "CACHE DROP -> %s + %s%s (note deleted)",
        cache.NOTES_LIST_KEY,
        cache.NOTE_KEY_PREFIX,
        note_id,
    )
