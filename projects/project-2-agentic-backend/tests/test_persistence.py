"""Que el historial sobreviva el viaje a Postgres sin deformarse.

El test que importa de verdad es `test_los_pares_de_tools_sobreviven`: es el
invariante del que depende todo lo demás. Si se rompe, cada request posterior de
esa sesión le manda a la API un historial inválido.
"""

import pytest
from anthropic.types import TextBlock, ToolUseBlock
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ChatSession, Message
from app.repository import (
    SessionNotFoundError,
    dump_blocks,
    get_session,
    load_history,
    save_turn,
)

# Un turno de ejemplo con la forma exacta que tiene uno real.
TURNO_CON_TOOLS = [
    {"role": "user", "content": "¿cuánto es 42 por 2?"},
    {
        "role": "assistant",
        "content": [
            {"type": "text", "text": "Voy a calcularlo."},
            {
                "type": "tool_use",
                "id": "toolu_1",
                "name": "calculate",
                "input": {"expression": "42 * 2"},
            },
        ],
    },
    {
        # El tool_result va con rol "user": desde la perspectiva del modelo, vos
        # sos el usuario.
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "84"}],
    },
    {"role": "assistant", "content": [{"type": "text", "text": "42 por 2 es 84."}]},
]


def _ids_de(historial: list[dict], tipo: str, campo: str) -> set[str]:
    """Junta los ids de un tipo de bloque a lo largo de todo un historial."""
    return {
        bloque[campo]
        for mensaje in historial
        for bloque in mensaje["content"]
        if bloque["type"] == tipo
    }


# ---------------------------------------------------------------------------
# Serialización — sin base, es código puro
# ---------------------------------------------------------------------------


def test_dump_blocks_convierte_objetos_del_sdk():
    """Lo que devuelve la API son modelos Pydantic, no dicts."""
    bloques = dump_blocks(
        [
            TextBlock(type="text", text="Voy a calcularlo."),
            ToolUseBlock(
                type="tool_use", id="toolu_1", name="calculate", input={"expression": "1+1"}
            ),
        ]
    )

    assert bloques[0]["type"] == "text"
    assert bloques[1]["id"] == "toolu_1"
    # `input` es un dict libre del modelo y se conserva tal cual.
    assert bloques[1]["input"] == {"expression": "1+1"}

    # exclude_none=True: los opcionales vacíos no se guardan, así no se los
    # reenviamos después a la API.
    assert "citations" not in bloques[0]


def test_dump_blocks_normaliza_un_content_string():
    """La API acepta content como string; la columna guarda siempre bloques.

    Sin esta normalización el bug sería silencioso: un string es iterable, así que
    se guardaría una lista de caracteres.
    """
    assert dump_blocks("hola") == [{"type": "text", "text": "hola"}]


def test_dump_blocks_es_idempotente():
    """Un historial que salió de la base tiene que poder volver a entrar."""
    bloques = [{"type": "text", "text": "hola"}]
    assert dump_blocks(dump_blocks(bloques)) == bloques


# ---------------------------------------------------------------------------
# El invariante
# ---------------------------------------------------------------------------


def test_los_pares_de_tools_sobreviven(db: Session, chat: ChatSession):
    """Guardar y recargar no puede romper la correlación por tool_use_id.

    Si falla, la API rechaza el turno siguiente con "tool_use ids were found
    without tool_result blocks".
    """
    save_turn(db, chat.id, TURNO_CON_TOOLS)

    recargado = load_history(db, chat.id)

    assert _ids_de(recargado, "tool_use", "id") == {"toolu_1"}
    assert _ids_de(recargado, "tool_result", "tool_use_id") == {"toolu_1"}


def test_el_historial_vuelve_completo_y_en_orden(db: Session, chat: ChatSession):
    """No alcanza con que estén los bloques: el orden es parte de la validez."""
    save_turn(db, chat.id, TURNO_CON_TOOLS)

    recargado = load_history(db, chat.id)

    assert [m["role"] for m in recargado] == ["user", "assistant", "user", "assistant"]
    # El bloque de texto del assistant no se perdió al guardar el tool_use: se
    # persiste el mensaje entero, no sólo la parte interesante.
    assert recargado[1]["content"][0]["text"] == "Voy a calcularlo."
    assert recargado[1]["content"][1]["type"] == "tool_use"


def test_historial_vacio(db: Session, chat: ChatSession):
    """Una sesión recién creada no tiene historial, y eso no es un error."""
    assert load_history(db, chat.id) == []


# ---------------------------------------------------------------------------
# Posiciones y turnos
# ---------------------------------------------------------------------------


def test_los_turnos_se_numeran_y_las_posiciones_siguen(db: Session, chat: ChatSession):
    """Dos turnos seguidos: el numerado sube, las posiciones continúan.

    Que las posiciones no se reinicien por turno es lo que hace que ORDER BY
    position ordene el historial entero y no cada turno por separado.
    """
    primero = save_turn(db, chat.id, TURNO_CON_TOOLS)
    segundo = save_turn(db, chat.id, [{"role": "user", "content": "¿y por 3?"}])

    assert (primero, segundo) == (1, 2)

    filas = db.execute(
        select(Message.turn, Message.position)
        .where(Message.session_id == chat.id)
        .order_by(Message.position)
    ).all()

    assert [f.position for f in filas] == [0, 1, 2, 3, 4]
    assert [f.turn for f in filas] == [1, 1, 1, 1, 2]


def test_el_segundo_turno_ve_el_primero(db: Session, chat: ChatSession):
    """La memoria, que es todo el punto: el historial se acumula."""
    save_turn(db, chat.id, TURNO_CON_TOOLS)
    save_turn(db, chat.id, [{"role": "user", "content": "¿y por 3?"}])

    recargado = load_history(db, chat.id)

    assert len(recargado) == 5
    assert recargado[-1]["content"] == [{"type": "text", "text": "¿y por 3?"}]


# ---------------------------------------------------------------------------
# Contadores y errores
# ---------------------------------------------------------------------------


def test_los_tokens_se_acumulan_por_separado(db: Session, chat: ChatSession):
    """Input y output tienen precios distintos: un contador único no serviría."""
    save_turn(db, chat.id, TURNO_CON_TOOLS, input_tokens=400, output_tokens=60)
    save_turn(
        db,
        chat.id,
        [{"role": "user", "content": "otra"}],
        input_tokens=550,
        output_tokens=40,
    )

    recargada = get_session(db, chat.id)

    assert recargada.input_tokens_used == 950
    assert recargada.output_tokens_used == 100


def test_sesion_inexistente(db: Session):
    """El repositorio levanta un error de dominio, no devuelve None.

    Así la ruta lo traduce a un 404 sin tener que adivinar qué significa un None
    que llegó desde tres capas más abajo.
    """
    with pytest.raises(SessionNotFoundError):
        get_session(db, "s_no_existe")


def test_guardar_en_una_sesion_inexistente_no_escribe_nada(db: Session):
    """save_turn valida la sesión ANTES de insertar mensajes."""
    with pytest.raises(SessionNotFoundError):
        save_turn(db, "s_no_existe", TURNO_CON_TOOLS)

    huerfanos = (
        db.execute(select(Message).where(Message.session_id == "s_no_existe")).scalars().all()
    )
    assert huerfanos == []
