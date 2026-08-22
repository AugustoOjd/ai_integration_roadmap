import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.note import Note
from app.schemas.note import NoteCreate, NoteResponse, SearchRequest, SearchResult
from app.services.embeddings import embedding_service
from app.services.search import search_notes

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notes", tags=["notes"])


@router.post("/", response_model=NoteResponse, status_code=status.HTTP_201_CREATED)
async def create_note(note_in: NoteCreate, db: AsyncSession = Depends(get_db)):
    # Se embebe title + content: buscar solo por el cuerpo perdería el título,
    # que suele ser la parte más informativa.
    embedding = await embedding_service.embed(f"{note_in.title}\n{note_in.content}")

    print(len(embedding), embedding[:5])
    # La lista de floats la convierte a `vector` el tipo Vector de la columna.
    note = Note(title=note_in.title, content=note_in.content, embedding=embedding)
    db.add(note)
    await db.commit()
    await db.refresh(note)
    return note


@router.post("/search", response_model=list[SearchResult])
async def search(payload: SearchRequest, db: AsyncSession = Depends(get_db)):
    """Búsqueda semántica: ordena por cercanía de significado, no por palabras."""
    rows = await search_notes(db, payload.query, payload.top_k)
    logger.info("SEARCH %r -> %d resultados", payload.query, len(rows))

    # El servicio devuelve (Note, similarity); aquí se fusionan en un schema.
    return [
        SearchResult(**NoteResponse.model_validate(note).model_dump(), similarity=similarity)
        for note, similarity in rows
    ]


@router.get("/", response_model=list[NoteResponse])
async def list_notes(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Note).order_by(Note.created_at.desc()))
    return result.scalars().all()


# Después de /search: si esta ruta fuera antes y compartiera método, "search"
# se leería como un note_id.
@router.get("/{note_id}", response_model=NoteResponse)
async def get_note(note_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    note = await db.get(Note, note_id)
    if note is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
    return note
