"""Fase 4 — la traza como dato.

Lo que se verifica acá no es que el agente funcione (eso es la Fase 9, con el
modelo mockeado), sino que la traza tenga las propiedades que la hacen útil:
que sobreviva a los fallos, que no crezca sin límite, que se pueda paginar, y
que sea tan privada como la conversación que describe.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChatSession
from app.repository import (
    MAX_TOOL_OUTPUT_CHARS,
    load_steps,
    record_step,
    session_stats,
)


async def _sembrar(db: AsyncSession, session_id: str, cantidad: int = 3) -> None:
    """Unos pasos de traza, como los dejaría el loop."""
    for i in range(1, cantidad + 1):
        await record_step(
            db,
            session_id=session_id,
            turn=1,
            iteration=i,
            tool_name="calculate",
            tool_input={"expression": f"{i} * 2"},
            tool_output=str(i * 2),
            latency_ms=i,
            # Como en el loop real: los tokens sólo en el primer paso de cada
            # vuelta. Acá cada vuelta tiene un paso, así que van en todos.
            input_tokens=100 * i,
            output_tokens=10 * i,
        )


# ---------------------------------------------------------------------------
# Escritura
# ---------------------------------------------------------------------------


async def test_un_paso_se_guarda_con_sus_coordenadas(db: AsyncSession, chat: ChatSession):
    """Turno e iteración son lo que ubica un paso dentro de la conversación."""
    await record_step(
        db,
        session_id=chat.id,
        turn=2,
        iteration=3,
        tool_name="get_my_orders",
        tool_input={},
        tool_output='[{"order_id": "o_1"}]',
        latency_ms=12,
    )

    (paso,) = await load_steps(db, chat.id)

    assert (paso.turn, paso.iteration) == (2, 3)
    assert paso.tool_name == "get_my_orders"
    assert paso.is_error is False


async def test_el_output_largo_se_recorta(db: AsyncSession, chat: ChatSession):
    """Una tool que devuelve 200 KB no puede inflar esta tabla.

    A diferencia del contexto —donde el tamaño se paga en tokens en cada
    vuelta— acá el problema es que nadie va a leer eso entero nunca.
    """
    enorme = "x" * (MAX_TOOL_OUTPUT_CHARS + 5_000)

    await record_step(
        db,
        session_id=chat.id,
        turn=1,
        iteration=1,
        tool_name="search",
        tool_input={"query": "algo"},
        tool_output=enorme,
    )

    (paso,) = await load_steps(db, chat.id)

    assert len(paso.tool_output) < len(enorme)
    # El recorte AVISA que recortó, con cuánto falta. Un recorte silencioso hace
    # que un dato truncado parezca un dato completo.
    assert paso.tool_output.endswith("[+5000 chars]")


async def test_un_paso_fallido_queda_registrado(db: AsyncSession, chat: ChatSession):
    """Un error de tool no es un error del request, pero sí es algo que contar.

    "Qué porcentaje de llamadas a `search` falla" es una métrica, y sale de acá.
    """
    await record_step(
        db,
        session_id=chat.id,
        turn=1,
        iteration=1,
        tool_name="search",
        tool_input={"query": "x"},
        tool_output="timeout",
        is_error=True,
    )

    (paso,) = await load_steps(db, chat.id)
    assert paso.is_error is True


async def test_la_traza_sobrevive_aunque_el_turno_no_se_guarde(
    db: AsyncSession, chat: ChatSession
):
    """LA propiedad de la fase.

    `record_step` commitea en el acto justamente para esto: si el loop explota
    en la vuelta 3, las vueltas 1 y 2 son lo que vas a querer mirar. Acá se
    simula el fallo con un rollback posterior — la traza tiene que seguir ahí.
    """
    await _sembrar(db, chat.id, cantidad=2)

    # Algo falla después de la traza y la unidad de trabajo se descarta.
    await db.rollback()

    assert len(await load_steps(db, chat.id)) == 2


# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------


async def test_la_traza_viene_mas_nueva_primero(db: AsyncSession, chat: ChatSession):
    """Lo último que pasó es lo que casi siempre estás buscando."""
    await _sembrar(db, chat.id, cantidad=3)

    pasos = await load_steps(db, chat.id)

    assert [p.iteration for p in pasos] == [3, 2, 1]


async def test_paginacion_por_cursor(db: AsyncSession, chat: ChatSession):
    """`before_id` y no `OFFSET`.

    Con offset, un paso nuevo al principio corre todo hacia atrás mientras
    alguien pagina y la página 2 repite filas de la 1.
    """
    await _sembrar(db, chat.id, cantidad=5)

    primera = await load_steps(db, chat.id, limit=2)
    segunda = await load_steps(db, chat.id, limit=2, before_id=primera[-1].id)

    assert [p.iteration for p in primera] == [5, 4]
    assert [p.iteration for p in segunda] == [3, 2]
    # Ni un solo elemento repetido entre páginas.
    assert not ({p.id for p in primera} & {p.id for p in segunda})


async def test_el_resumen_se_calcula_en_la_base(db: AsyncSession, chat: ChatSession):
    """`GROUP BY`, no traer todo a Python y contar."""
    await _sembrar(db, chat.id, cantidad=3)
    await record_step(
        db,
        session_id=chat.id,
        turn=1,
        iteration=4,
        tool_name="search",
        tool_input={"query": "x"},
        tool_output="boom",
        is_error=True,
    )

    stats = await session_stats(db, chat.id)

    assert stats["total_steps"] == 4
    assert stats["failed_steps"] == 1
    assert stats["tools"] == {"calculate": 3, "search": 1}
    assert stats["input_tokens"] == 600  # 100 + 200 + 300
    assert stats["output_tokens"] == 60


# ---------------------------------------------------------------------------
# El endpoint
# ---------------------------------------------------------------------------


async def test_get_log(client: AsyncClient, db: AsyncSession, chat: ChatSession):
    await _sembrar(db, chat.id, cantidad=2)

    respuesta = await client.get(f"/sessions/{chat.id}/log", headers={"X-User-Id": "u_42"})

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert len(cuerpo["steps"]) == 2
    assert cuerpo["stats"]["total_steps"] == 2
    # No vino una página completa, así que no hay más.
    assert cuerpo["next_before_id"] is None


async def test_el_log_de_otro_usuario_no_se_ve(
    client: AsyncClient, db: AsyncSession, chat: ChatSession
):
    """La traza es tan privada como la conversación. Más, incluso: tiene los
    argumentos exactos con los que se llamó a cada tool.

    Y responde 404, no 403: distinguirlos permitiría enumerar sesiones ajenas.
    """
    await _sembrar(db, chat.id, cantidad=1)

    respuesta = await client.get(f"/sessions/{chat.id}/log", headers={"X-User-Id": "u_7"})

    assert respuesta.status_code == 404


async def test_sin_autenticacion_no_hay_log(client: AsyncClient, chat: ChatSession):
    respuesta = await client.get(f"/sessions/{chat.id}/log")

    assert respuesta.status_code == 401


@pytest.mark.parametrize("limit", [0, 201])
async def test_limit_fuera_de_rango(client: AsyncClient, chat: ChatSession, limit: int):
    """El tope del `limit` lo pone el servidor, no el cliente.

    Sin `le=200`, un `?limit=1000000` es una forma gratis de hacerle levantar a
    tu base toda la tabla en una query.
    """
    respuesta = await client.get(
        f"/sessions/{chat.id}/log", params={"limit": limit}, headers={"X-User-Id": "u_42"}
    )

    assert respuesta.status_code == 422
