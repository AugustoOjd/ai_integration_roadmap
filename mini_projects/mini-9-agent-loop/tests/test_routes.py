"""Fase 9 — la capa HTTP: códigos y forma de la respuesta.

Los tests de acá NO verifican lógica de agente (para eso está `test_agent.py`):
verifican el contrato. Qué código devuelve cada situación, qué campos trae el
body, y qué NO trae.

Ese último punto es el que más se olvida. Un endpoint que filtra un campo de más
no falla ningún test a menos que alguien escriba el assert que dice "esto no
tiene que estar".
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChatSession
from tests.conftest import response, text

CABECERA = {"X-User-Id": "u_42"}


# ---------------------------------------------------------------------------
# Crear y ver sesiones
# ---------------------------------------------------------------------------


async def test_crear_sesion(client: AsyncClient):
    """201 Created, y sin body: el dueño sale del header autenticado."""
    respuesta = await client.post("/sessions", headers=CABECERA)

    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert cuerpo["user_id"] == "u_42"
    assert cuerpo["session_id"].startswith("s_")
    assert cuerpo["status"] == "active"
    assert cuerpo["budget_remaining"] == cuerpo["budget_tokens"]


async def test_crear_sesion_sin_autenticacion(client: AsyncClient):
    respuesta = await client.post("/sessions")

    assert respuesta.status_code == 401


async def test_la_respuesta_no_expone_los_contadores_internos(client: AsyncClient):
    """La respuesta es una PROYECCIÓN del modelo, no el modelo.

    `input_tokens_used` existe en la tabla y no aparece acá: afuera se expone
    "cuánto te queda", que es la pregunta que alguien se hace, no "cuánto
    llevás gastado en tokens de entrada".
    """
    cuerpo = (await client.post("/sessions", headers=CABECERA)).json()

    assert "input_tokens_used" not in cuerpo
    assert "output_tokens_used" not in cuerpo


async def test_ver_una_sesion(client: AsyncClient, chat: ChatSession):
    respuesta = await client.get(f"/sessions/{chat.id}", headers=CABECERA)

    assert respuesta.status_code == 200
    assert respuesta.json()["session_id"] == chat.id


async def test_una_sesion_ajena_es_404(client: AsyncClient, chat: ChatSession):
    """404 y no 403.

    Distinguirlos convertiría al endpoint en un oráculo: probando ids se podría
    averiguar qué sesiones existen sin poder verlas. Misma razón por la que un
    login dice "credenciales inválidas" y no "ese usuario no existe".
    """
    respuesta = await client.get(f"/sessions/{chat.id}", headers={"X-User-Id": "u_7"})

    assert respuesta.status_code == 404


async def test_una_sesion_inexistente_es_404(client: AsyncClient):
    respuesta = await client.get("/sessions/s_no_existe", headers=CABECERA)

    assert respuesta.status_code == 404


# ---------------------------------------------------------------------------
# Mandar mensajes
# ---------------------------------------------------------------------------


async def test_un_turno_devuelve_su_traza(
    client: AsyncClient, chat: ChatSession, fake_model
):
    """Sin `iterations`, `tools_used` y `usage`, un agente en producción es una
    caja negra que no podés ni debuggear ni costear."""
    fake_model(response(text("Hola."), tokens=(120, 8)))

    respuesta = await client.post(
        f"/sessions/{chat.id}/messages", headers=CABECERA, json={"prompt": "hola"}
    )

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["answer"] == "Hola."
    assert cuerpo["iterations"] == 1
    assert cuerpo["tools_used"] == []
    assert cuerpo["usage"] == {"input_tokens": 120, "output_tokens": 8}
    assert cuerpo["budget_remaining"] == 10_000 - 120


@pytest.mark.parametrize("prompt", ["", "x" * 8_001])
async def test_prompt_invalido(client: AsyncClient, chat: ChatSession, prompt: str):
    """El `max_length` no es burocracia.

    Sin tope, un prompt de 500 KB entra al historial, se persiste, y se REENVÍA
    en cada vuelta del loop y en cada turno futuro de la sesión. Un solo request
    encarece la conversación entera para siempre.
    """
    respuesta = await client.post(
        f"/sessions/{chat.id}/messages", headers=CABECERA, json={"prompt": prompt}
    )

    assert respuesta.status_code == 422


async def test_no_convergio_es_422(client: AsyncClient, chat: ChatSession, fake_model):
    """No falló nadie: ni el cliente mandó algo inválido, ni el proveedor se
    cayó. La tarea, como está planteada, no se pudo resolver con estas tools."""
    from tests.conftest import tool_use

    fake_model(
        *[
            response(tool_use(f"t{i}", "calculate", expression="1+1"), stop_reason="tool_use")
            for i in range(12)
        ]
    )

    respuesta = await client.post(
        f"/sessions/{chat.id}/messages", headers=CABECERA, json={"prompt": "loopeá"}
    )

    assert respuesta.status_code == 422


async def test_el_error_de_la_api_no_se_filtra(
    client: AsyncClient, chat: ChatSession, fake_model, monkeypatch
):
    """Todo lo que devolvés puede terminar en la pantalla de un usuario.

    Un `BadRequestError` hacia Anthropic es un bug NUESTRO (típicamente un par
    `tool_use`/`tool_result` roto). El detalle va al log; al cliente, un 500
    genérico.
    """
    from unittest.mock import AsyncMock, MagicMock

    import httpx
    from anthropic import BadRequestError

    fake = MagicMock()
    fake.messages.count_tokens = AsyncMock(
        return_value=MagicMock(input_tokens=10)
    )
    fake.messages.create = AsyncMock(
        side_effect=BadRequestError(
            message="messages.1: tool_use ids were found without tool_result blocks",
            response=httpx.Response(400, request=httpx.Request("POST", "http://x")),
            body=None,
        )
    )
    monkeypatch.setattr("app.agent.get_async_client", lambda: fake)

    respuesta = await client.post(
        f"/sessions/{chat.id}/messages", headers=CABECERA, json={"prompt": "hola"}
    )

    assert respuesta.status_code == 500
    assert "tool_use" not in respuesta.text


# ---------------------------------------------------------------------------
# Documentación
# ---------------------------------------------------------------------------


async def test_el_openapi_declara_el_202(client: AsyncClient):
    """El 202 lo arma un exception handler, no la ruta.

    Se declara igual en `responses=` porque si no, un cliente que lee el schema
    no se entera de que este endpoint puede no devolverle una respuesta.
    """
    esquema = (await client.get("/openapi.json")).json()
    codigos = esquema["paths"]["/sessions/{session_id}/messages"]["post"]["responses"]

    assert "202" in codigos
    assert "409" in codigos
