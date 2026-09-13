"""Capa 2: el loop, con el modelo mockeado.

Acá vive el 80% de los bugs de un agente, porque acá vive todo lo que es fácil
escribir mal sin que dé error: el historial, la correlación de ids, el corte
del loop, y la regla de que los `tool_result` van juntos.

La técnica es guionar la conversación: le decimos al fake qué contestar en cada
llamada y verificamos CON QUÉ lo llamó el agente. Nada de esto necesita red.
"""

import pytest

from app.agent import MaxIterationsError, run_agent
from tests.conftest import response, text, tool_use


async def test_sin_tools_una_sola_llamada(fake_model):
    """Si el modelo contesta de una, el loop no da vueltas de más."""
    fake = fake_model(response(text("Hola, soy un agente."), stop_reason="end_turn"))

    result = await run_agent("hola")

    assert result.text == "Hola, soy un agente."
    assert result.tools_used == []
    assert result.iterations == 1
    assert fake.messages.create.await_count == 1


async def test_una_ronda_arma_bien_el_historial(fake_model):
    """El test más importante de la suite: la forma del historial.

    Verifica las tres reglas de la Fase 2 de una sola vez.
    """
    fake = fake_model(
        response(
            tool_use("toolu_1", "calculate", expression="4823 * 1917"),
            stop_reason="tool_use",
        ),
        response(text("Da 9245691."), stop_reason="end_turn"),
    )

    result = await run_agent("¿cuánto es 4823 por 1917?")

    assert result.text == "Da 9245691."
    assert result.tools_used == ["calculate"]
    assert result.iterations == 2

    # El historial con el que se hizo la SEGUNDA llamada.
    messages = fake.messages.create.await_args_list[1].kwargs["messages"]

    # Regla: tres mensajes, no dos.
    assert len(messages) == 3
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]

    # Regla: el assistant se reenvía COMPLETO, con su bloque `tool_use` adentro.
    # Si alguien "optimiza" guardando sólo el texto, este assert se pone rojo.
    assert any(block.type == "tool_use" for block in messages[1]["content"])

    # Regla: el result cita el id EXACTO del pedido.
    resultado = messages[2]["content"][0]
    assert resultado["type"] == "tool_result"
    assert resultado["tool_use_id"] == "toolu_1"
    assert resultado["content"] == "9245691.0"
    assert resultado["is_error"] is False


async def test_dos_tools_del_mismo_turno_van_en_un_solo_mensaje(fake_model):
    """La regla de la Fase 6, y la razón por la que existe este test.

    Partir los `tool_result` en dos mensajes NO da error: el request funciona.
    Lo que hace es enseñarle al modelo, turno a turno, a dejar de pedir tools en
    paralelo. Degrada solo, se paga en latencia, y jamás se relaciona con la
    causa.

    Un bug silencioso es exactamente lo que un test tiene que atrapar.
    """
    fake = fake_model(
        response(
            tool_use("toolu_1", "get_current_time"),
            tool_use("toolu_2", "calculate", expression="100 * 2"),
            stop_reason="tool_use",
        ),
        response(text("Listo."), stop_reason="end_turn"),
    )

    result = await run_agent("¿qué hora es? y cuánto es 100 por 2")

    # Dos tools, UNA sola vuelta: eso es paralelo, no encadenado.
    assert result.tools_used == ["get_current_time", "calculate"]
    assert result.iterations == 2

    messages = fake.messages.create.await_args_list[1].kwargs["messages"]
    assert len(messages) == 3  # user + assistant + UN mensaje de resultados
    assert len(messages[2]["content"]) == 2  # con los dos bloques adentro

    # Y en el orden en que los pidió, no en el orden en que terminaron: los ids
    # tienen que corresponderse con sus pedidos.
    assert [b["tool_use_id"] for b in messages[2]["content"]] == ["toolu_1", "toolu_2"]


async def test_tool_alucinada_no_mata_la_corrida(fake_model):
    """Un fallo de tool es un dato para el modelo, no el fin de la conversación."""
    fake = fake_model(
        response(
            tool_use("toolu_1", "send_email", to="juan@example.com"),
            stop_reason="tool_use",
        ),
        response(text("No puedo mandar mails."), stop_reason="end_turn"),
    )

    result = await run_agent("mandale un mail a juan")

    assert result.text == "No puedo mandar mails."

    resultado = fake.messages.create.await_args_list[1].kwargs["messages"][2]["content"][0]
    # El flag es lo que le dice al modelo "esto falló, no lo tomes como dato".
    # Sin él, un mensaje de error parece la respuesta de la tool.
    assert resultado["is_error"] is True
    assert "send_email" in resultado["content"]


async def test_error_inesperado_no_filtra_detalles_al_modelo(fake_model, monkeypatch):
    """Seguridad: lo que entra en un `tool_result` el modelo lo puede repetir.

    Un traceback puede traer rutas, queries o credenciales, y la respuesta del
    modelo va directo al usuario. Al modelo se le manda un mensaje genérico; el
    detalle queda en el log del servidor.
    """

    def explota(expression: str) -> float:
        raise ConnectionError("falló contra db.internal user=admin password=hunter2")

    monkeypatch.setattr("app.tools.calculator._evaluate", explota)

    fake = fake_model(
        response(tool_use("toolu_1", "calculate", expression="2+2"), stop_reason="tool_use"),
        response(text("No pude calcularlo."), stop_reason="end_turn"),
    )

    await run_agent("cuánto es 2+2")

    contenido = fake.messages.create.await_args_list[1].kwargs["messages"][2]["content"][0]
    assert contenido["is_error"] is True
    assert "hunter2" not in contenido["content"]
    assert "db.internal" not in contenido["content"]


async def test_corta_al_llegar_al_tope(fake_model):
    """Sin esto, un modelo confundido pide tools para siempre."""
    pidiendo_siempre = [
        response(tool_use(f"toolu_{i}", "get_current_time"), stop_reason="tool_use")
        for i in range(10)
    ]
    fake_model(*pidiendo_siempre)

    with pytest.raises(MaxIterationsError):
        await run_agent("dame la hora para siempre", max_iterations=3)


async def test_acumula_los_tokens_de_todas_las_vueltas(fake_model):
    """El usage es POR request. Sin sumarlo, subestimás el costo real."""
    fake_model(
        response(
            tool_use("toolu_1", "get_current_time"),
            stop_reason="tool_use",
            tokens=(100, 20),
        ),
        response(text("Listo."), stop_reason="end_turn", tokens=(150, 30)),
    )

    result = await run_agent("qué hora es")

    assert result.input_tokens == 250
    assert result.output_tokens == 50


async def test_respuesta_truncada_se_devuelve_igual(fake_model):
    """`max_tokens` no es un error: es una respuesta incompleta.

    El loop tiene que salir (no es `tool_use`) y devolver lo que haya, con un
    warning en el log. Lo que no puede hacer es quedarse dando vueltas.
    """
    fake_model(response(text("La respuesta es"), stop_reason="max_tokens"))

    result = await run_agent("escribime una novela")

    assert result.text == "La respuesta es"
    assert result.iterations == 1
