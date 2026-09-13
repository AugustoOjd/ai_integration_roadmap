"""Fixtures compartidas.

La regla de esta suite: **ningún test llama al modelo**. Son lentos, cuestan
plata y no son determinísticos — un test que a veces pasa es peor que no tener
test, porque te entrena a ignorar el rojo.

Lo que sí se testea es todo lo demás, que es casi todo: las tools son funciones
puras, y el loop es orquestación sobre respuestas que podemos fabricar.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from anthropic.types import Message, TextBlock, ToolUseBlock, Usage
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


# ---------------------------------------------------------------------------
# Fábricas de respuestas
# ---------------------------------------------------------------------------
# Usamos los tipos REALES del SDK y no diccionarios sueltos. Cuesta un poco más
# y vale la pena: si una versión nueva del SDK cambia la forma de un bloque,
# estos tests se rompen al construirlos. Ese rojo es exactamente la alarma que
# querés — con dicts falsos, el cambio pasaría desapercibido hasta producción.


def text(content: str) -> TextBlock:
    return TextBlock(type="text", text=content)


def tool_use(tool_id: str, name: str, **tool_input) -> ToolUseBlock:
    return ToolUseBlock(type="tool_use", id=tool_id, name=name, input=tool_input)


def response(*blocks, stop_reason: str = "end_turn", tokens: tuple[int, int] = (10, 5)) -> Message:
    """Una respuesta del modelo, fabricada a mano."""
    return Message(
        id="msg_test",
        type="message",
        role="assistant",
        model="claude-haiku-4-5",
        content=list(blocks),
        stop_reason=stop_reason,
        usage=Usage(input_tokens=tokens[0], output_tokens=tokens[1]),
    )


@pytest.fixture
def fake_model(monkeypatch):
    """Reemplaza el cliente de Anthropic por uno que devuelve lo que vos digas.

    Devuelve una función: le pasás las respuestas en orden y te da el mock del
    cliente, para después inspeccionar CON QUÉ se lo llamó.

    Se parchea `get_async_client` y no `run_agent`: si mockearas `run_agent` no
    estarías testeando nada: es justamente el código bajo prueba. La frontera
    correcta para el mock es la más externa posible — acá, la llamada HTTP.
    """

    def _configure(*responses: Message) -> MagicMock:
        fake = MagicMock()
        # `side_effect` con una lista devuelve un elemento por llamada, en
        # orden. Es lo que nos deja guionar una conversación entera: primero
        # pide una tool, después contesta.
        fake.messages.create = AsyncMock(side_effect=list(responses))
        monkeypatch.setattr("app.agent.get_async_client", lambda: fake)
        return fake

    return _configure
