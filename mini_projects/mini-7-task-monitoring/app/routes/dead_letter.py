from fastapi import APIRouter, Query

from app.schemas import ClearResponse, DeadLetterPage, ReplayResponse
from app.services import dead_letter

router = APIRouter(prefix="/dead-letter", tags=["dead-letter"])


@router.get("", response_model=DeadLetterPage)
def list_dead_letter(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> DeadLetterPage:
    """Los fallos definitivos, del más reciente al más viejo.

    Paginado y con techo: la DLQ puede tener miles de entradas y devolverlas
    todas en una respuesta es la forma de convertir un incidente en dos.
    """
    return DeadLetterPage(
        total=dead_letter.count(),
        entries=dead_letter.list_failures(limit=limit, offset=offset),
    )


@router.post("/replay", response_model=ReplayResponse)
def replay_dead_letter(
    limit: int = Query(default=50, ge=1, le=500),
) -> ReplayResponse:
    """Reencola los fallos y los saca de la DLQ.

    Es POST y no GET porque modifica dos sistemas: encola trabajo nuevo y vacía
    entradas. No es idempotente — llamarlo dos veces con la DLQ llena encola dos
    veces.

    Es DELIBERADAMENTE manual. Reencolar automático desde la DLQ recrea el bucle
    que la DLQ vino a cortar: si la causa sigue presente, las tareas vuelven a
    fallar, vuelven a la DLQ y vuelven a reenviarse, para siempre. El flujo
    correcto es: alguien mira, entiende, arregla, y RECIÉN AHÍ llama a esto.
    """
    return ReplayResponse(reenviadas=dead_letter.replay(limit=limit))


@router.delete("", response_model=ClearResponse)
def clear_dead_letter() -> ClearResponse:
    """Descarta los fallos sin reprocesarlos. Para cuando ya se analizaron."""
    return ClearResponse(descartadas=dead_letter.clear())
