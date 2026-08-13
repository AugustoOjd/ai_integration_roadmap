import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mini_1_crud_api.database import get_db
from mini_1_crud_api.models.note import Note
from mini_1_crud_api.schemas.note import NoteCreate, NoteResponse, NoteUpdate

# prefix="/notes" means every path below is actually /notes, /notes/{note_id}, etc.
router = APIRouter(prefix="/notes", tags=["notes"])


@router.get("/", response_model=list[NoteResponse])
async def list_notes(db: AsyncSession = Depends(get_db)):
    # Depends(get_db) runs get_db() for this request and injects the yielded session
    result = await db.execute(select(Note).order_by(Note.created_at.desc()))
    return result.scalars().all()  # unwraps Row objects into plain Note instances


@router.post("/", response_model=NoteResponse, status_code=status.HTTP_201_CREATED)
async def create_note(note_in: NoteCreate, db: AsyncSession = Depends(get_db)):
    # note_in was already validated against NoteCreate by FastAPI before this ran
    note = Note(title=note_in.title, content=note_in.content)
    db.add(note)  # stages the INSERT
    await db.commit()  # actually executes it
    await db.refresh(note)  # pulls back DB-generated fields (id default, created_at)
    return note


@router.get("/{note_id}", response_model=NoteResponse)
async def get_note(note_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    # db.get() is a primary-key lookup — no need to build a select() for this
    note = await db.get(Note, note_id)
    if note is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
    return note


@router.put("/{note_id}", response_model=NoteResponse)
async def update_note(note_id: uuid.UUID, note_in: NoteUpdate, db: AsyncSession = Depends(get_db)):
    note = await db.get(Note, note_id)
    if note is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")

    # Mutating the loaded object is enough; SQLAlchemy tracks the change
    # and commit() below turns it into an UPDATE statement
    note.title = note_in.title
    note.content = note_in.content
    await db.commit()
    await db.refresh(note)
    return note


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_note(note_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    note = await db.get(Note, note_id)
    if note is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")

    await db.delete(note)
    await db.commit()
    # 204 No Content: no return value, FastAPI sends an empty response body
