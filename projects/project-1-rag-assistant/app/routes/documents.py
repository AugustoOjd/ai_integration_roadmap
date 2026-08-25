import logging
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.document import Document, DocumentChunk
from app.schemas.document import ChunkResponse, DocumentResponse
from app.services.cache import bump_corpus_version
from app.services.documents import ExtractionError, chunk_text, extract_document
from app.services.embeddings import embedding_service

logger = logging.getLogger(__name__)

# Todo este router va detras de require_api_key: son operaciones de
# administracion, se llaman desde un servidor y nunca desde un navegador.
router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    # File(...) marca que viene en multipart/form-data, no en el body JSON.
    # UploadFile lo maneja Starlette: en memoria si es chico, en disco si crece.
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    if not file.filename:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "El archivo no tiene nombre")

    # Se mira .size antes de leer, para no cargar el archivo en RAM primero.
    if file.size is not None and file.size > settings.MAX_UPLOAD_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"Maximo {settings.MAX_UPLOAD_BYTES // 1024 // 1024}MB",
        )

    contenido = await file.read()

    try:
        extraido = extract_document(contenido, file.filename)
    except ExtractionError as exc:
        # 422 y no 500: el archivo llego bien, es su contenido el que no sirve.
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    trozos = chunk_text(extraido.text)

    # Por lotes, no uno a uno: cientos de chunks de uno en uno tardan un orden
    # de magnitud mas.
    vectores = await embedding_service.embed_many([t.text for t in trozos])

    logger.info("%s -> %d chars, %d chunks", file.filename, len(extraido.text), len(trozos))

    # Los chunks se asignan a la relacion, no se insertan aparte: SQLAlchemy
    # rellena document_id solo y todo va en un unico commit.
    documento = Document(
        filename=file.filename,
        original_text=extraido.text,
        chunks=[
            DocumentChunk(
                chunk_text=trozo.text,
                chunk_index=i,
                embedding=vector,
                # La pagina sale del offset del chunk en el texto completo.
                page=extraido.page_at(trozo.start),
            )
            for i, (trozo, vector) in enumerate(zip(trozos, vectores, strict=True))
        ],
    )
    db.add(documento)
    await db.commit()
    await db.refresh(documento)

    # El corpus cambio: las respuestas cacheadas ya no reflejan lo que hay.
    await bump_corpus_version()

    return DocumentResponse(
        id=documento.id,
        filename=documento.filename,
        chunks_count=len(trozos),
        created_at=documento.created_at,
    )


@router.get("/", response_model=list[DocumentResponse])
async def list_documents(db: AsyncSession = Depends(get_db)):
    # COUNT en SQL, no len(doc.chunks): esto ultimo dispararia una consulta por
    # documento (N+1) y traeria todo el texto solo para contarlo.
    stmt = (
        select(Document, func.count(DocumentChunk.id).label("chunks_count"))
        # outerjoin y no join: un documento sin chunks debe aparecer con 0.
        .outerjoin(DocumentChunk, DocumentChunk.document_id == Document.id)
        .group_by(Document.id)
        .order_by(Document.created_at.desc())
    )
    filas = await db.execute(stmt)

    return [
        DocumentResponse(
            id=doc.id,
            filename=doc.filename,
            chunks_count=chunks_count,
            created_at=doc.created_at,
        )
        for doc, chunks_count in filas
    ]


@router.get("/{document_id}/chunks", response_model=list[ChunkResponse])
async def get_chunks(document_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    # Se comprueba el documento aparte para distinguir "no existe" (404) de
    # "existe pero no tiene chunks" (lista vacia).
    if await db.get(Document, document_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")

    stmt = (
        select(DocumentChunk)
        .where(DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_index)
    )
    return (await db.execute(stmt)).scalars().all()


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(document_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Borra el documento y sus chunks. Necesario para re-ingerir al ajustar
    CHUNK_SIZE."""
    documento = await db.get(Document, document_id)
    if documento is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")

    # El cascade del relationship se encarga de los chunks.
    await db.delete(documento)
    await db.commit()
    await bump_corpus_version()
