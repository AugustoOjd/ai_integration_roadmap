from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.config import settings


class Message(BaseModel):
    """Un turno previo de la conversacion, enviado por el cliente."""

    # El prompt de sistema lo pone siempre el servidor, en services/prompt.py.
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=settings.MAX_HISTORY_CHARS)


class ChatRequest(BaseModel):
    """Body de POST /chat.

    El historial vive en el cliente, asi que su tamano lo decide el cliente:
    aqui se recorta antes de llegar al modelo.
    """

    query: str = Field(min_length=1, max_length=2000)
    history: list[Message] = Field(default_factory=list)

    @model_validator(mode="after")
    def _recortar_historial(self) -> "ChatRequest":
        # Ventana deslizante: los ultimos N turnos. Convierte el coste de
        # crecer en cada mensaje a ser constante.
        recorte = self.history[-settings.MAX_HISTORY_TURNS :]

        # Y ademas un tope en caracteres, porque N turnos pueden ser enormes.
        total = 0
        conservados: list[Message] = []
        for mensaje in reversed(recorte):
            total += len(mensaje.content)
            if total > settings.MAX_HISTORY_CHARS:
                break
            conservados.append(mensaje)

        self.history = list(reversed(conservados))
        return self


class Source(BaseModel):
    """De donde salio una afirmacion. El numero casa con las citas [1], [2]."""

    n: int
    source: str
    page: int | None
    similarity: float


class ChatResponse(BaseModel):
    answer: str
    sources: list[Source]
