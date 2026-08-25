from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.query import SearchRequest, SearchResponse, SearchResult
from app.services.search import search_chunks

# POST aunque sea una lectura: una query larga no cabe comoda en una URL.
# Es la misma decision que toman Elasticsearch y OpenSearch.
router = APIRouter(prefix="/search", tags=["search"])


@router.post("/query", response_model=SearchResponse)
async def search(payload: SearchRequest, db: AsyncSession = Depends(get_db)):
    """Recuperacion sin LLM.

    Existe para poder separar los dos fallos posibles del RAG: si la respuesta
    es mala, aqui se ve si el problema fue recuperar los chunks equivocados o
    generar mal a partir de los correctos.
    """
    hits = await search_chunks(db, payload.query, payload.top_k)

    return SearchResponse(
        query=payload.query,
        results=[
            SearchResult(
                source=hit.source,
                page=hit.page,
                section=hit.section,
                chunk=hit.text,
                similarity=hit.similarity,
            )
            for hit in hits
        ],
    )
