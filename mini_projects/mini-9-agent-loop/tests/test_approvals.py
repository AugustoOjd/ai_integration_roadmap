"""Fase 5 — que una tool sensible frene el loop en vez de ejecutarse.

El test que sostiene la fase es `test_la_tool_sensible_no_se_ejecuta`, y lo que
lo hace válido es CÓMO verifica: mirando la tabla `orders`, no la respuesta del
agente. Que el agente diga "no la ejecuté" no prueba nada — es texto generado
por un modelo. Que la fila siga en `pending`, sí.
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import ApprovalRequired, run_agent
from app.deps import AgentDeps
from app.models import (
    ApprovalStatus,
    ChatSession,
    Order,
    OrderStatus,
    PendingApproval,
    SessionStatus,
)
from app.policy import requiere_aprobacion
from app.repository import load_history, load_steps, pendientes_de
from tests.conftest import response, text, tool_use


@pytest.fixture
async def pedido(db: AsyncSession) -> Order:
    """Un pedido cancelable de u_42."""
    orden = Order(id="o_991", user_id="u_42", item="Silla", amount_cents=78_000)
    db.add(orden)
    await db.commit()
    return orden


# ---------------------------------------------------------------------------
# La política
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tool", "espera_aprobacion"),
    [
        ("cancel_order", True),
        ("send_email", True),
        ("refund", True),
        # Leer nunca necesita permiso.
        ("get_my_orders", False),
        ("get_order", False),
        ("calculate", False),
        ("get_current_time", False),
    ],
)
def test_la_politica(tool: str, espera_aprobacion: bool):
    """El criterio: irreversible o visible para afuera → aprobación."""
    assert requiere_aprobacion(tool) is espera_aprobacion


# ---------------------------------------------------------------------------
# La pausa
# ---------------------------------------------------------------------------


async def test_la_tool_sensible_no_se_ejecuta(
    db: AsyncSession, chat: ChatSession, deps: AgentDeps, pedido: Order, fake_model
):
    """EL test de la fase, verificado contra la BASE y no contra la respuesta."""
    fake_model(
        response(
            text("Voy a cancelarlo."),
            tool_use("toolu_7", "cancel_order", order_id="o_991"),
            stop_reason="tool_use",
        )
    )

    with pytest.raises(ApprovalRequired):
        await run_agent(db, chat.id, "cancelá el pedido o_991", deps)

    # La prueba: el pedido sigue pendiente. No se canceló nada.
    await db.refresh(pedido)
    assert pedido.status is OrderStatus.PENDING


async def test_la_pausa_deja_el_pendiente_en_la_base(
    db: AsyncSession, chat: ChatSession, deps: AgentDeps, pedido: Order, fake_model
):
    """Sin esta fila, retomar sería imposible: no sabrías qué ibas a ejecutar."""
    fake_model(
        response(
            tool_use("toolu_7", "cancel_order", order_id="o_991"),
            stop_reason="tool_use",
        )
    )

    with pytest.raises(ApprovalRequired) as exc:
        await run_agent(db, chat.id, "cancelá el o_991", deps)

    (pendiente,) = await pendientes_de(db, chat.id)

    assert pendiente.tool_use_id == "toolu_7"
    assert pendiente.tool_name == "cancel_order"
    # Los argumentos exactos: quien aprueba tiene que ver QUÉ está aprobando.
    assert pendiente.tool_input == {"order_id": "o_991"}
    assert pendiente.status is ApprovalStatus.PENDING
    assert pendiente.expires_at is not None
    # La excepción lleva lo mismo adentro, para que el handler no reconsulte.
    assert exc.value.aprobaciones[0].tool_use_id == "toolu_7"


async def test_la_sesion_queda_pausada(
    db: AsyncSession, chat: ChatSession, deps: AgentDeps, pedido: Order, fake_model
):
    """El status es lo que hace cumplir el invariante: nada más entra acá."""
    fake_model(
        response(tool_use("toolu_7", "cancel_order", order_id="o_991"), stop_reason="tool_use")
    )

    with pytest.raises(ApprovalRequired):
        await run_agent(db, chat.id, "cancelá el o_991", deps)

    await db.refresh(chat)
    assert chat.status is SessionStatus.PENDING_APPROVAL


async def test_el_turno_parcial_se_persiste_con_el_tool_use(
    db: AsyncSession, chat: ChatSession, deps: AgentDeps, pedido: Order, fake_model
):
    """El historial queda CON un `tool_use` sin cerrar, y es correcto.

    La regla de la Fase 1, precisada: no es "el historial nunca tiene pares
    abiertos", es "una sesión ACTIVA tiene un historial válido". Ésta no está
    activa. El par se cierra cuando llegue la decisión.

    Persistirlo es lo que permite que la Fase 6 reconstruya la corrida desde un
    request distinto en vez de tener que recordarla en memoria.
    """
    fake_model(
        response(
            text("Voy a cancelarlo."),
            tool_use("toolu_7", "cancel_order", order_id="o_991"),
            stop_reason="tool_use",
        )
    )

    with pytest.raises(ApprovalRequired):
        await run_agent(db, chat.id, "cancelá el o_991", deps)

    historial = await load_history(db, chat.id)

    assert [m["role"] for m in historial] == ["user", "assistant"]
    bloques = historial[1]["content"]
    assert bloques[0]["text"] == "Voy a cancelarlo."
    assert bloques[1]["id"] == "toolu_7"
    # Y no hay ningún tool_result todavía.
    assert not [b for m in historial for b in m["content"] if b["type"] == "tool_result"]


async def test_ninguna_tool_del_turno_se_ejecuta(
    db: AsyncSession, chat: ChatSession, deps: AgentDeps, pedido: Order, fake_model
):
    """Ni las inocentes.

    Dos razones: los `tool_result` de un turno van todos en UN mensaje (no podés
    mandar uno ahora y otro mañana), y si la decisión es "no", ese trabajo se
    tiró.
    """
    fake_model(
        response(
            tool_use("toolu_1", "calculate", expression="2+2"),
            tool_use("toolu_2", "cancel_order", order_id="o_991"),
            stop_reason="tool_use",
        )
    )

    with pytest.raises(ApprovalRequired):
        await run_agent(db, chat.id, "sumá 2+2 y cancelá el o_991", deps)

    # `calculate` no dejó traza porque no corrió.
    assert await load_steps(db, chat.id) == []


async def test_una_tool_normal_no_pausa_nada(
    db: AsyncSession, chat: ChatSession, deps: AgentDeps, fake_model
):
    """El camino de siempre sigue funcionando: la Fase 5 no rompió la 2."""
    fake_model(
        response(tool_use("toolu_1", "calculate", expression="42*2"), stop_reason="tool_use"),
        response(text("Son 84."), stop_reason="end_turn"),
    )

    resultado = await run_agent(db, chat.id, "cuánto es 42*2", deps)

    assert resultado.text == "Son 84."
    assert await pendientes_de(db, chat.id) == []
    await db.refresh(chat)
    assert chat.status is SessionStatus.ACTIVE


# ---------------------------------------------------------------------------
# La capa HTTP
# ---------------------------------------------------------------------------


async def test_el_endpoint_devuelve_202(
    client: AsyncClient, db: AsyncSession, chat: ChatSession, pedido: Order, fake_model
):
    """202 y no 200 con un flag.

    Un cliente que no mira el flag trataría un pedido de permiso como una
    respuesta. El código de estado existe justamente para no depender de que el
    cliente lea bien el body.
    """
    fake_model(
        response(tool_use("toolu_7", "cancel_order", order_id="o_991"), stop_reason="tool_use")
    )

    respuesta = await client.post(
        f"/sessions/{chat.id}/messages",
        headers={"X-User-Id": "u_42"},
        json={"prompt": "cancelá el pedido o_991"},
    )

    assert respuesta.status_code == 202
    cuerpo = respuesta.json()
    assert cuerpo["status"] == "pending_approval"
    assert cuerpo["pending"][0] == {
        "tool_use_id": "toolu_7",
        "tool_name": "cancel_order",
        "tool_input": {"order_id": "o_991"},
        "expires_at": cuerpo["pending"][0]["expires_at"],
    }


async def test_una_sesion_pausada_rechaza_mensajes(
    client: AsyncClient, db: AsyncSession, chat: ChatSession, pedido: Order, fake_model
):
    """409 Conflict: el pedido es válido, choca con el estado del recurso.

    Sin esto, el segundo mensaje arrancaría un turno nuevo sobre un historial
    con un `tool_use` sin cerrar, y la API lo rechazaría con un 400
    incomprensible.
    """
    fake_model(
        response(tool_use("toolu_7", "cancel_order", order_id="o_991"), stop_reason="tool_use")
    )

    await client.post(
        f"/sessions/{chat.id}/messages",
        headers={"X-User-Id": "u_42"},
        json={"prompt": "cancelá el o_991"},
    )

    segundo = await client.post(
        f"/sessions/{chat.id}/messages",
        headers={"X-User-Id": "u_42"},
        json={"prompt": "hola?"},
    )

    assert segundo.status_code == 409


async def test_el_pendiente_es_unico_por_tool_use_id(db: AsyncSession, chat: ChatSession):
    """El candado de idempotencia de la Fase 6, a nivel base.

    Dos aprobaciones del mismo `tool_use_id` no pueden existir: hay una sola
    fila, y su `status` es el que dice si ya se decidió.
    """
    comunes = {
        "session_id": chat.id,
        "tool_use_id": "toolu_7",
        "turn": 1,
        "tool_name": "cancel_order",
        "tool_input": {},
        "expires_at": datetime.now(UTC) + timedelta(hours=1),
    }
    db.add_all([PendingApproval(**comunes), PendingApproval(**comunes)])

    with pytest.raises(IntegrityError):
        await db.commit()


async def test_no_quedan_pendientes_de_otras_sesiones(db: AsyncSession, chat: ChatSession):
    """`pendientes_de` filtra por sesión. Obvio, y por eso mismo fácil de romper."""
    otra = ChatSession(user_id="u_42", budget_tokens=1000)
    db.add(otra)
    await db.flush()

    db.add(
        PendingApproval(
            session_id=otra.id,
            tool_use_id="toolu_x",
            turn=1,
            tool_name="refund",
            tool_input={},
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    await db.commit()

    assert await pendientes_de(db, chat.id) == []
    assert len(await pendientes_de(db, otra.id)) == 1


async def test_la_query_de_huerfanos_encuentra_la_pausa(db: AsyncSession, chat: ChatSession, deps, pedido, fake_model):
    """Lo mismo que la consulta de QUERIES.md, pero como test.

    Durante una pausa el historial TIENE un huérfano. Sirve para dejar claro que
    esa consulta detecta un estado legítimo además de un bug: lo que la
    distingue es el `status` de la sesión.
    """
    fake_model(
        response(tool_use("toolu_7", "cancel_order", order_id="o_991"), stop_reason="tool_use")
    )

    with pytest.raises(ApprovalRequired):
        await run_agent(db, chat.id, "cancelá el o_991", deps)

    historial = await load_history(db, chat.id)
    pedidos = {b["id"] for m in historial for b in m["content"] if b["type"] == "tool_use"}
    resultados = {
        b["tool_use_id"] for m in historial for b in m["content"] if b["type"] == "tool_result"
    }

    assert pedidos - resultados == {"toolu_7"}

    # Y la sesión NO está activa, que es lo que lo vuelve legítimo.
    sesion = (await db.execute(select(ChatSession).where(ChatSession.id == chat.id))).scalar_one()
    assert sesion.status is SessionStatus.PENDING_APPROVAL
