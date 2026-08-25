import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.llm import generate, generate_stream
from app.services.prompt import build_messages
from app.services.search import SearchHit, search_chunks

logger = logging.getLogger(__name__)

SIN_CONTEXTO = (
    "No encontre nada en los documentos cargados que responda a esa pregunta."
)


@dataclass(frozen=True)
class RagAnswer:
    text: str
    sources: list[SearchHit] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0


def _consulta_de_busqueda(question: str, history: list[dict]) -> str:
    """Contextualiza una pregunta de seguimiento.

    "y cuantos tiene?" no contiene ningun termino del corpus, asi que buscarla
    tal cual no recupera nada. Se le antepone el ultimo turno del usuario para
    que arrastre el tema.

    Heuristica: si el usuario cambia de tema de golpe, mete ruido. La version
    precisa seria pedirle al LLM que reescriba la pregunta como autocontenida.
    """
    if not history:
        return question

    ultimo = next((m["content"] for m in reversed(history) if m["role"] == "user"), "")

    # Si el turno anterior es la misma pregunta, anteponerlo solo la duplicaria.
    if not ultimo or ultimo.strip().lower() == question.strip().lower():
        return question

    return f"{ultimo} {question}"


async def answer(
    db: AsyncSession,
    question: str,
    history: list[dict] | None = None,
) -> RagAnswer:
    """El pipeline completo: recuperar, ensamblar, generar."""
    history = history or []

    # Se busca con la consulta contextualizada, pero al LLM se le pasa la
    # pregunta original: el historial ya le da el contexto por su lado.
    hits = await search_chunks(db, _consulta_de_busqueda(question, history), settings.TOP_K)

    # Corto antes de llamar al LLM si nada del corpus se parece a la pregunta.
    # Ahorra la llamada y evita que el modelo rellene el hueco inventando.
    if not hits or hits[0].similarity < settings.MIN_SIMILARITY:
        mejor = hits[0].similarity if hits else 0.0
        logger.info("RAG %r -> sin contexto (mejor similitud %.3f)", question, mejor)
        return RagAnswer(text=SIN_CONTEXTO)

    messages = build_messages(question, hits, history)
    respuesta = await generate(messages)

    return RagAnswer(
        text=respuesta.text,
        sources=hits,
        prompt_tokens=respuesta.prompt_tokens,
        completion_tokens=respuesta.completion_tokens,
    )


async def answer_stream(
    db: AsyncSession,
    question: str,
    history: list[dict] | None = None,
) -> tuple[list[SearchHit], AsyncIterator[str]]:
    """Como answer(), pero devuelve las fuentes y un iterador del texto.

    Las fuentes se resuelven ANTES de generar, asi la ruta puede mandarlas como
    primer evento: el front pinta las citas mientras la respuesta se escribe.
    """
    history = history or []
    hits = await search_chunks(db, _consulta_de_busqueda(question, history), settings.TOP_K)

    if not hits or hits[0].similarity < settings.MIN_SIMILARITY:
        mejor = hits[0].similarity if hits else 0.0
        logger.info("RAG %r -> sin contexto (mejor similitud %.3f)", question, mejor)

        async def _sin_contexto() -> AsyncIterator[str]:
            yield SIN_CONTEXTO

        return [], _sin_contexto()

    return hits, generate_stream(build_messages(question, hits, history))
