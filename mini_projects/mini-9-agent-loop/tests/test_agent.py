"""Fase 9 — el loop, con el cliente mockeado.

Ésta es la capa donde vive el 80% de los bugs de un agente: no en las tools
(funciones puras) ni en los endpoints (Pydantic los cuida), sino en la
orquestación — qué se le manda al modelo, en qué orden, y qué se guarda.

Por eso casi todos los asserts de acá miran `fake.messages.create.call_args`:
lo que importa no es sólo qué devolvió el agente, sino **con qué historial habló
con el modelo**.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import MaxIterationsError, run_agent
from app.deps import AgentDeps
from app.models import ChatSession
from app.repository import load_history, load_steps
from tests.conftest import response, text, tool_use


def historial_enviado(fake, llamada: int = -1) -> list[dict]:
    """Los `messages` con los que se llamó al modelo en una vuelta dada."""
    return fake.messages.create.call_args_list[llamada].kwargs["messages"]


# ---------------------------------------------------------------------------
# La memoria
# ---------------------------------------------------------------------------


async def test_el_segundo_turno_le_manda_el_primero_al_modelo(
    db: AsyncSession, chat: ChatSession, deps: AgentDeps, fake_model
):
    """Todo el mini 9 en un assert.

    La Messages API es *stateless*: no guarda nada entre requests. Si el agente
    recuerda algo es porque se lo volvemos a contar entero, y esto verifica que
    se lo contamos.
    """
    fake = fake_model(
        response(text("Son 84.")),
        response(text("Son 252.")),
    )

    await run_agent(db, chat.id, "cuánto es 42 por 2", deps)
    await run_agent(db, chat.id, "¿y por 3?", deps)

    enviado = historial_enviado(fake)

    assert len(enviado) == 3
    assert enviado[0]["content"] == "cuánto es 42 por 2"
    assert enviado[1]["content"][0].text == "Son 84."
    assert enviado[2]["content"] == "¿y por 3?"


async def test_la_respuesta_del_assistant_se_persiste(
    db: AsyncSession, chat: ChatSession, deps: AgentDeps, fake_model
):
    """El bug clásico de la Fase 2: guardar el prompt y olvidar la respuesta.

    El síntoma es desconcertante — el agente "no recuerda lo que él mismo dijo"
    y el usuario que pregunta "¿y por 3?" no tiene a qué referirse.
    """
    fake_model(response(text("Son 84.")))

    await run_agent(db, chat.id, "cuánto es 42 por 2", deps)

    historial = await load_history(db, chat.id)
    assert [m["role"] for m in historial] == ["user", "assistant"]
    assert historial[1]["content"][0]["text"] == "Son 84."


async def test_el_input_crece_turno_a_turno(
    db: AsyncSession, chat: ChatSession, deps: AgentDeps, fake_model
):
    """El costo de la memoria, medido.

    No es un bug: el historial viaja completo en cada llamada. Es lo que la
    Fase 7 acota y la Fase 8 recorta.
    """
    fake = fake_model(response(text("a")), response(text("b")), response(text("c")))

    for prompt in ("uno", "dos", "tres"):
        await run_agent(db, chat.id, prompt, deps)

    largos = [len(historial_enviado(fake, i)) for i in range(3)]
    assert largos == [1, 3, 5]


# ---------------------------------------------------------------------------
# El protocolo de tools
# ---------------------------------------------------------------------------


async def test_el_mensaje_del_assistant_se_reenvia_completo(
    db: AsyncSession, chat: ChatSession, deps: AgentDeps, fake_model
):
    """La regla de la Fase 2 del mini 8: `response.content` entero, sin filtrar.

    Si se filtraran bloques, el `tool_use` desaparecería del historial y el
    `tool_result` del turno siguiente quedaría huérfano.
    """
    fake = fake_model(
        response(
            text("Voy a calcularlo."),
            tool_use("toolu_1", "calculate", expression="42*2"),
            stop_reason="tool_use",
        ),
        response(text("Son 84.")),
    )

    await run_agent(db, chat.id, "cuánto es 42 por 2", deps)

    enviado = historial_enviado(fake)
    bloques_assistant = enviado[1]["content"]

    # Los DOS bloques, no sólo el `tool_use`.
    assert [b.type for b in bloques_assistant] == ["text", "tool_use"]


async def test_todos_los_tool_results_van_en_un_solo_mensaje(
    db: AsyncSession, chat: ChatSession, deps: AgentDeps, fake_model
):
    """Partirlos no da error: da algo peor.

    El modelo lee ese historial como el ejemplo de cómo se hacen las cosas acá,
    y turno a turno aprende a NO pedir tools en paralelo. Degrada solo, se paga
    en latencia, y nadie lo relaciona nunca con la causa.
    """
    fake_model(
        response(
            tool_use("toolu_1", "calculate", expression="2+2"),
            tool_use("toolu_2", "calculate", expression="3+3"),
            stop_reason="tool_use",
        ),
        response(text("4 y 6.")),
    )

    await run_agent(db, chat.id, "sumá 2+2 y 3+3", deps)

    historial = await load_history(db, chat.id)
    mensajes_con_resultados = [
        m for m in historial if any(b["type"] == "tool_result" for b in m["content"])
    ]

    assert len(mensajes_con_resultados) == 1
    assert len(mensajes_con_resultados[0]["content"]) == 2


async def test_dos_tools_en_paralelo_son_una_sola_vuelta(
    db: AsyncSession, chat: ChatSession, deps: AgentDeps, fake_model
):
    """La diferencia entre una vuelta con dos tools y dos vueltas con una."""
    fake_model(
        response(
            tool_use("toolu_1", "calculate", expression="2+2"),
            tool_use("toolu_2", "get_current_time"),
            stop_reason="tool_use",
        ),
        response(text("listo")),
    )

    resultado = await run_agent(db, chat.id, "sumá y decime la hora", deps)

    assert resultado.iterations == 2  # la de las tools + la de la respuesta final
    assert resultado.tools_used == ["calculate", "get_current_time"]


async def test_tools_used_conserva_repetidos_y_orden(
    db: AsyncSession, chat: ChatSession, deps: AgentDeps, fake_model
):
    """Un `set` escondería justo el síntoma que estás buscando: el modelo
    llamando tres veces a la misma tool."""
    fake_model(
        response(tool_use("t1", "calculate", expression="1+1"), stop_reason="tool_use"),
        response(tool_use("t2", "calculate", expression="2+2"), stop_reason="tool_use"),
        response(text("listo")),
    )

    resultado = await run_agent(db, chat.id, "sumá dos veces", deps)

    assert resultado.tools_used == ["calculate", "calculate"]


# ---------------------------------------------------------------------------
# Errores y cortes
# ---------------------------------------------------------------------------


async def test_una_tool_que_falla_no_mata_la_corrida(
    db: AsyncSession, chat: ChatSession, deps: AgentDeps, fake_model
):
    """Un error de tool no es un error del request: es información.

    Si la excepción se escapara, `gather` la propagaría, el turno se armaría sin
    ese bloque, y la API rechazaría el request entero — un fallo en una tool se
    convertiría en un fallo de toda la conversación.
    """
    fake_model(
        # Expresión inválida: el evaluador AST la rechaza.
        response(
            tool_use("toolu_1", "calculate", expression="__import__('os')"),
            stop_reason="tool_use",
        ),
        response(text("No pude calcular eso.")),
    )

    resultado = await run_agent(db, chat.id, "calculá algo raro", deps)

    assert resultado.text == "No pude calcular eso."

    historial = await load_history(db, chat.id)
    (bloque,) = [b for m in historial for b in m["content"] if b["type"] == "tool_result"]
    assert bloque["is_error"] is True

    # Y quedó en la traza, que es de donde sale "qué porcentaje de llamadas a
    # esta tool falla".
    (paso,) = await load_steps(db, chat.id)
    assert paso.is_error is True


async def test_una_tool_inventada_no_rompe_nada(
    db: AsyncSession, chat: ChatSession, deps: AgentDeps, fake_model
):
    """Los modelos alucinan nombres de tools. Es esperable, no excepcional."""
    fake_model(
        response(tool_use("toolu_1", "tool_que_no_existe"), stop_reason="tool_use"),
        response(text("Perdón, me confundí.")),
    )

    resultado = await run_agent(db, chat.id, "hacé algo", deps)

    assert resultado.text == "Perdón, me confundí."


async def test_max_iterations_corta(
    db: AsyncSession, chat: ChatSession, deps: AgentDeps, fake_model
):
    """Sin tope, un modelo confundido pide la misma tool para siempre."""
    fake_model(
        *[
            response(tool_use(f"t{i}", "calculate", expression="1+1"), stop_reason="tool_use")
            for i in range(5)
        ]
    )

    with pytest.raises(MaxIterationsError):
        await run_agent(db, chat.id, "loopeá", deps, max_iterations=3)


async def test_un_turno_que_no_converge_no_se_guarda(
    db: AsyncSession, chat: ChatSession, deps: AgentDeps, fake_model
):
    """La sesión queda como estaba y el usuario puede reintentar sobre una
    conversación sana.

    La alternativa —persistir el turno trunco— dejaría un `tool_result` que el
    modelo nunca llegó a interpretar, y todo turno futuro arrancaría desde ese
    estado raro.
    """
    fake_model(
        *[
            response(tool_use(f"t{i}", "calculate", expression="1+1"), stop_reason="tool_use")
            for i in range(5)
        ]
    )

    with pytest.raises(MaxIterationsError):
        await run_agent(db, chat.id, "loopeá", deps, max_iterations=2)

    assert await load_history(db, chat.id) == []

    # Pero la traza SÍ quedó: es justamente lo que vas a querer mirar.
    assert len(await load_steps(db, chat.id)) == 2


async def test_max_tokens_no_se_hace_pasar_por_respuesta_final(
    db: AsyncSession, chat: ChatSession, deps: AgentDeps, fake_model
):
    """Se corta a la mitad, se avisa en el log, y se devuelve lo que hay.

    Es la decisión del mini 8 y sigue siendo la misma: no hay forma de
    "completar" una respuesta truncada sin volver a llamar al modelo.
    """
    fake_model(response(text("Estaba diciendo que"), stop_reason="max_tokens"))

    resultado = await run_agent(db, chat.id, "contame algo largo", deps)

    assert resultado.text == "Estaba diciendo que"
