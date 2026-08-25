import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass

from openai import APIError, AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """Fallo hablando con el proveedor. La ruta lo traduce a un 5xx."""


# API compatible con OpenAI: Anthropic, Groq, Ollama y OpenAI hablan la misma,
# asi que cambiar de proveedor es cambiar LLM_BASE_URL y LLM_MODEL en el .env.
# El `or` cubre el caso de valor ausente, que el constructor no admite.
client = AsyncOpenAI(
    base_url=settings.LLM_BASE_URL,
    api_key=settings.LLM_API_KEY or "sin-configurar",
)


@dataclass(frozen=True)
class LLMAnswer:
    text: str
    prompt_tokens: int
    completion_tokens: int


async def generate(messages: list[dict]) -> LLMAnswer:
    """Una llamada al modelo. Devuelve el texto y lo que costo."""
    try:
        respuesta = await client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=messages,
            # El tope de coste por peticion: sin el, una pregunta pidiendo un
            # ensayo larguisimo se paga entera.
            max_tokens=settings.MAX_RESPONSE_TOKENS,
            temperature=settings.TEMPERATURE,
        )
    except APIError as exc:
        logger.error("LLM: %s", exc)
        raise LLMError(str(exc)) from exc

    texto = respuesta.choices[0].message.content or ""
    uso = respuesta.usage

    logger.info(
        "LLM %s -> %d prompt + %d completion tokens",
        settings.LLM_MODEL,
        uso.prompt_tokens if uso else 0,
        uso.completion_tokens if uso else 0,
    )

    return LLMAnswer(
        text=texto.strip(),
        prompt_tokens=uso.prompt_tokens if uso else 0,
        completion_tokens=uso.completion_tokens if uso else 0,
    )


async def generate_stream(messages: list[dict]) -> AsyncIterator[str]:
    """Igual que generate() pero cediendo el texto segun llega.

    La diferencia no es de velocidad total sino de latencia percibida: el
    usuario ve la primera palabra en ~300ms en vez de esperar la respuesta
    entera.
    """
    try:
        stream = await client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=messages,
            max_tokens=settings.MAX_RESPONSE_TOKENS,
            temperature=settings.TEMPERATURE,
            stream=True,
        )
        async for evento in stream:
            if not evento.choices:
                continue
            # delta.content es None en el primer y ultimo evento del stream.
            if trozo := evento.choices[0].delta.content:
                yield trozo
    except APIError as exc:
        logger.error("LLM stream: %s", exc)
        raise LLMError(str(exc)) from exc
