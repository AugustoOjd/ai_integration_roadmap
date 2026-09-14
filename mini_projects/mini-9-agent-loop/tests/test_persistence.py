"""Fase 1 — que el historial sobreviva el viaje a Postgres sin deformarse.

El test que importa de verdad es `test_los_pares_de_tools_sobreviven`: es el
invariante del que depende todo el resto del mini. Si se rompe, cada request
posterior de esa sesión le manda a la API un historial inválido.
"""

import pytest
from anthropic.types import TextBlock, ToolUseBlock
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChatSession, Message
from app.repository import (
    SessionNotFoundError,
    dump_blocks,
    get_session,
    load_history,
    save_turn,
)

# ---------------------------------------------------------------------------
# Un turno de ejemplo, con la forma exacta que tiene uno real
# ---------------------------------------------------------------------------

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
        # El `tool_result` va con rol "user": desde la perspectiva del modelo,
        # vos sos el usuario.
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
            ToolUseBlock(type="tool_use", id="toolu_1", name="calculate", input={"expression": "1+1"}),
        ]
    )

    assert bloques[0]["type"] == "text"
    assert bloques[1]["id"] == "toolu_1"
    # `input` es un dict libre del modelo y se conserva tal cual: no es asunto
    # nuestro qué mandó adentro.
    assert bloques[1]["input"] == {"expression": "1+1"}

    # `exclude_none=True`: los opcionales que vinieron vacíos no se guardan, así
    # no se los reenviamos después a la API.
    assert "citations" not in bloques[0]


def test_dump_blocks_normaliza_un_content_string():
    """La API acepta `content` como string; la columna guarda siempre bloques.

    Sin esta normalización el bug sería silencioso: un string es iterable, así
    que se guardaría una lista de caracteres.
    """
    assert dump_blocks("hola") == [{"type": "text", "text": "hola"}]


def test_dump_blocks_es_idempotente():
    """Un historial que salió de la base tiene que poder volver a entrar."""
    bloques = [{"type": "text", "text": "hola"}]
    assert dump_blocks(dump_blocks(bloques)) == bloques


# ---------------------------------------------------------------------------
# El invariante de la fase
# ---------------------------------------------------------------------------


async def test_los_pares_de_tools_sobreviven(db: AsyncSession, chat: ChatSession):
    """Guardar y recargar no puede romper la correlación por `tool_use_id`.

    Éste es EL test del mini. Si falla, la API rechaza el turno siguiente con
    "tool_use ids were found without tool_result blocks".
    """
    await save_turn(db, chat.id, TURNO_CON_TOOLS)

    recargado = await load_history(db, chat.id)

    assert _ids_de(recargado, "tool_use", "id") == {"toolu_1"}
    assert _ids_de(recargado, "tool_result", "tool_use_id") == {"toolu_1"}


async def test_el_historial_vuelve_completo_y_en_orden(db: AsyncSession, chat: ChatSession):
    """No alcanza con que estén los bloques: el orden es parte de la validez.

    Un `tool_result` antes de su `tool_use` es un request rechazado.
    """
    await save_turn(db, chat.id, TURNO_CON_TOOLS)

    recargado = await load_history(db, chat.id)

    assert [m["role"] for m in recargado] == ["user", "assistant", "user", "assistant"]
    # El bloque de texto del assistant NO se perdió al guardar el `tool_use`:
    # el mensaje entero se persiste, no sólo la parte interesante.
    assert recargado[1]["content"][0]["text"] == "Voy a calcularlo."
    assert recargado[1]["content"][1]["type"] == "tool_use"


async def test_historial_vacio(db: AsyncSession, chat: ChatSession):
    """Una sesión recién creada no tiene historial, y eso no es un error."""
    assert await load_history(db, chat.id) == []


# ---------------------------------------------------------------------------
# Posiciones y turnos
# ---------------------------------------------------------------------------


async def test_los_turnos_se_numeran_y_las_posiciones_siguen(
    db: AsyncSession, chat: ChatSession
):
    """Dos turnos seguidos: el numerado sube, las posiciones continúan.

    Que las posiciones no se reinicien por turno es lo que hace que
    `ORDER BY position` ordene el historial ENTERO y no cada turno por separado.
    """
    primero = await save_turn(db, chat.id, TURNO_CON_TOOLS)
    segundo = await save_turn(
        db, chat.id, [{"role": "user", "content": "¿y por 3?"}]
    )

    assert (primero, segundo) == (1, 2)

    filas = (
        await db.execute(
            select(Message.turn, Message.position)
            .where(Message.session_id == chat.id)
            .order_by(Message.position)
        )
    ).all()

    assert [f.position for f in filas] == [0, 1, 2, 3, 4]
    assert [f.turn for f in filas] == [1, 1, 1, 1, 2]


async def test_el_segundo_turno_ve_el_primero(db: AsyncSession, chat: ChatSession):
    """La memoria, que es todo el punto del mini: el historial se acumula."""
    await save_turn(db, chat.id, TURNO_CON_TOOLS)
    await save_turn(db, chat.id, [{"role": "user", "content": "¿y por 3?"}])

    recargado = await load_history(db, chat.id)

    assert len(recargado) == 5
    assert recargado[-1]["content"] == [{"type": "text", "text": "¿y por 3?"}]


# ---------------------------------------------------------------------------
# Contadores y errores
# ---------------------------------------------------------------------------


async def test_los_tokens_se_acumulan_por_separado(db: AsyncSession, chat: ChatSession):
    """Input y output tienen precios distintos: un contador único no serviría."""
    await save_turn(db, chat.id, TURNO_CON_TOOLS, input_tokens=400, output_tokens=60)
    await save_turn(
        db,
        chat.id,
        [{"role": "user", "content": "otra"}],
        input_tokens=550,
        output_tokens=40,
    )

    recargada = await get_session(db, chat.id)

    assert recargada.input_tokens_used == 950
    assert recargada.output_tokens_used == 100


async def test_sesion_inexistente(db: AsyncSession):
    """El repositorio levanta un error de dominio, no devuelve None.

    Así la ruta puede traducirlo a un 404 sin tener que adivinar qué significa
    un None que llegó desde tres capas más abajo.
    """
    with pytest.raises(SessionNotFoundError):
        await get_session(db, "s_no_existe")


async def test_guardar_en_una_sesion_inexistente_no_escribe_nada(db: AsyncSession):
    """`save_turn` valida la sesión ANTES de insertar mensajes."""
    with pytest.raises(SessionNotFoundError):
        await save_turn(db, "s_no_existe", TURNO_CON_TOOLS)

    huerfanos = (
        await db.execute(select(Message).where(Message.session_id == "s_no_existe"))
    ).scalars().all()
    assert huerfanos == []
