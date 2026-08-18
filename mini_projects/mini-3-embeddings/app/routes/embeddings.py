import logging

from fastapi import APIRouter, HTTPException, status

from app.schemas.embedding import (
    CompareRequest,
    CompareResponse,
    EmbedRequest,
    EmbedResponse,
    ModelResult,
    SimilarityRequest,
    SimilarityResponse,
)
from app.services import embeddings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/embeddings", tags=["embeddings"])


def _resolve(alias: str) -> embeddings.EmbeddingService:
    """Translate a model alias into a service, or a 422 the caller can act on.

    get_service() raises KeyError, which would otherwise surface as a 500 — an
    unknown alias is the caller's mistake, not a server fault.
    """
    try:
        return embeddings.get_service(alias)
    except KeyError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/embed", response_model=EmbedResponse)
async def embed_text(request: EmbedRequest):
    """Turn one piece of text into its vector."""
    service = _resolve(request.model)
    vector = await service.embed(request.text)

    logger.info("EMBED -> %d dims via %r for %r", len(vector), request.model, request.text[:40])
    return EmbedResponse(
        text=request.text,
        model=service.model_name,
        embedding=vector,
        dimension=len(vector),
    )


@router.post("/similarity", response_model=SimilarityResponse)
async def compare_texts(request: SimilarityRequest):
    """Score how alike two pieces of text are, from -1 to 1."""
    service = _resolve(request.model)

    vector1 = await service.embed(request.text1)
    vector2 = await service.embed(request.text2)

    # Pure vector math on data already in memory — microseconds, no I/O, no model.
    # Generating costs ~15ms each; comparing is free by comparison.
    similarity = embeddings.cosine_similarity(vector1, vector2)

    logger.info("SIMILARITY -> %.4f via %r", similarity, request.model)
    return SimilarityResponse(
        text1=request.text1,
        text2=request.text2,
        model=service.model_name,
        similarity=similarity,
    )


@router.post("/compare-models", response_model=CompareResponse)
async def compare_models(request: CompareRequest):
    """Score the same pair of texts with EVERY configured model.

    This is what the class-with-instances design buys us: one module could only
    ever hold one model, so running the same comparison through several would be
    impossible without restarting the app.

    Worth doing because similarity scores are NOT comparable across models. Each
    model has its own scale — its own floor for unrelated text and its own ceiling
    for near-synonyms. Seeing two numbers for the same pair makes that concrete,
    and is the reason you should rank results rather than threshold them.

    Careful: the first call loads every model that isn't in memory yet, so it can
    take a while and pushes RAM up by roughly 1GB per model.
    """
    results: dict[str, ModelResult] = {}

    for alias, service in embeddings.SERVICES.items():
        vector1 = await service.embed(request.text1)
        vector2 = await service.embed(request.text2)

        results[alias] = ModelResult(
            model_name=service.model_name,
            dimension=service.dimension,
            similarity=embeddings.cosine_similarity(vector1, vector2),
        )

    logger.info(
        "COMPARE -> %s", {alias: round(r.similarity, 4) for alias, r in results.items()}
    )
    return CompareResponse(text1=request.text1, text2=request.text2, results=results)


@router.get("/models")
async def list_models():
    """Which models are configured, and which are actually in memory right now.

    `dimension` is only reported for loaded models — asking for it on the others
    would force a download, which a listing endpoint has no business doing.
    """
    return {
        alias: {
            "model_name": service.model_name,
            "loaded": service.is_loaded,
            "dimension": service.dimension if service.is_loaded else None,
        }
        for alias, service in embeddings.SERVICES.items()
    }
