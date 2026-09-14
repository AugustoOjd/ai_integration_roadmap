"""Fase 6 — retomar una corrida desde la base.

La propiedad que se verifica en todo el archivo: entre la pausa y la decisión,
**el estado vive en Postgres y en ningún otro lado**. Ningún test guarda nada en
memoria entre el `run_agent` que pausa y el `resume_run` que retoma; si el
proceso se hubiera reiniciado en el medio, todo seguiría funcionando igual.
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import (
    ApprovalRequired,
    resume_run,
    run_agent,
)
from app.deps import AgentDeps
from app.models import (
    ApprovalStatus,
    ChatSession,
    Order,
    OrderStatus,
    SessionStatus,
)
from app.repository import (
    ApprovalAlreadyDecidedError,
    ApprovalExpiredError,
    ApprovalNotFoundError,
    get_pending,
    load_history,
    pendientes_de,
)
from tests.conftest import response, text, tool_use

CABECERA = {"X-User-Id": "u_42"}


@pytest.fixture
async def pedido(db: AsyncSession) -> Order:
    orden = Order(id="o_991", user_id="u_42", item="Silla", amount_cents=78_000)
    db.add(orden)
    await db.commit()
    return orden


@pytest.fixture
async def pausada(
    db: AsyncSession, chat: ChatSession, deps: AgentDeps, pedido: Order, fake_model
) -> ChatSession:
    """Una sesión que ya quedó esperando aprobación de `cancel_order`.

    Guiona DOS respuestas: la que pide la tool (y provoca la pausa) y la que el
    modelo dará cuando se retome. La segunda se consume recién en el
    `resume_run` de cada test — un request después, que es justamente el punto.
    """
    fake_model(
        response(
            text("Voy a cancelarlo."),
            tool_use("toolu_7", "cancel_order", order_id="o_991"),
            stop_reason="tool_use",
        ),
        response(text("Listo, cancelé el pedido o_991."), stop_reason="end_turn"),
    )

    with pytest.raises(ApprovalRequired):
        await run_agent(db, chat.id, "cancelá el pedido o_991", deps)

    return chat


def _bloques(historial: list[dict], tipo: str) -> list[dict]:
    return [b for m in historial for b in m["content"] if b["type"] == tipo]


# ---------------------------------------------------------------------------
# Aprobar
# ---------------------------------------------------------------------------


async def test_aprobar_ejecuta_la_tool(
    db: AsyncSession, pausada: ChatSession, deps: AgentDeps, pedido: Order
):
    """Verificado contra la tabla `orders`, no contra el texto del agente."""
    resultado = await resume_run(db, pausada.id, "toolu_7", approved=True, deps=deps)

    await db.refresh(pedido)
    assert pedido.status is OrderStatus.CANCELLED
    assert resultado.text == "Listo, cancelé el pedido o_991."


async def test_aprobar_cierra_el_par_en_el_historial(
    db: AsyncSession, pausada: ChatSession, deps: AgentDeps
):
    """El invariante de la Fase 1 vuelve a cumplirse al retomar."""
    await resume_run(db, pausada.id, "toolu_7", approved=True, deps=deps)

    historial = await load_history(db, pausada.id)

    pedidos = {b["id"] for b in _bloques(historial, "tool_use")}
    resultados = {b["tool_use_id"] for b in _bloques(historial, "tool_result")}
    assert pedidos == resultados == {"toolu_7"}


async def test_la_sesion_vuelve_a_estar_activa(
    db: AsyncSession, pausada: ChatSession, deps: AgentDeps
):
    await resume_run(db, pausada.id, "toolu_7", approved=True, deps=deps)

    await db.refresh(pausada)
    assert pausada.status is SessionStatus.ACTIVE

    aprobacion = await get_pending(db, pausada.id, "toolu_7")
    assert aprobacion.status is ApprovalStatus.APPROVED
    assert aprobacion.decided_at is not None


# ---------------------------------------------------------------------------
# Rechazar
# ---------------------------------------------------------------------------


async def test_rechazar_no_ejecuta_la_tool(
    db: AsyncSession, pausada: ChatSession, deps: AgentDeps, pedido: Order
):
    await resume_run(db, pausada.id, "toolu_7", approved=False, deps=deps)

    await db.refresh(pedido)
    assert pedido.status is OrderStatus.PENDING


async def test_rechazar_produce_un_tool_result_con_is_error(
    db: AsyncSession, pausada: ChatSession, deps: AgentDeps
):
    """LA decisión de la fase.

    No se borra el `tool_use` —eso rompería el par y dejaría la sesión
    inservible—: se le contesta con un error. Es la misma mecánica que un fallo
    de tool en el mini 8, y el modelo sabe reaccionar a eso.
    """
    await resume_run(db, pausada.id, "toolu_7", approved=False, deps=deps)

    historial = await load_history(db, pausada.id)
    (resultado,) = _bloques(historial, "tool_result")

    assert resultado["tool_use_id"] == "toolu_7"
    assert resultado["is_error"] is True
    assert "no autorizó" in resultado["content"].lower()

    # Y el `tool_use` sigue ahí: el historial es un registro de lo que pasó,
    # incluido lo que se decidió no hacer.
    assert len(_bloques(historial, "tool_use")) == 1


async def test_rechazar_deja_traza(db: AsyncSession, pausada: ChatSession, deps: AgentDeps):
    """Una decisión humana es lo MÁS importante que puede haber en una auditoría."""
    from app.repository import load_steps

    await resume_run(db, pausada.id, "toolu_7", approved=False, deps=deps)

    (paso,) = await load_steps(db, pausada.id)
    assert paso.tool_name == "cancel_order"
    assert paso.is_error is True
    assert "rechazada" in paso.tool_output


# ---------------------------------------------------------------------------
# Idempotencia y vencimiento
# ---------------------------------------------------------------------------


async def test_aprobar_dos_veces_no_ejecuta_dos_veces(
    db: AsyncSession, pausada: ChatSession, deps: AgentDeps, pedido: Order
):
    """Dos clicks, un reintento de red, un cliente con retry: el mismo POST llega
    dos veces. Acá "dos veces" serían dos cancelaciones.

    El candado es el `status` de la fila, no la prolijidad del endpoint.
    """
    await resume_run(db, pausada.id, "toolu_7", approved=True, deps=deps)

    with pytest.raises(ApprovalAlreadyDecidedError):
        await resume_run(db, pausada.id, "toolu_7", approved=True, deps=deps)


async def test_rechazar_despues_de_aprobar_tampoco(
    db: AsyncSession, pausada: ChatSession, deps: AgentDeps
):
    """Una decisión tomada no se revierte por este camino."""
    await resume_run(db, pausada.id, "toolu_7", approved=True, deps=deps)

    with pytest.raises(ApprovalAlreadyDecidedError):
        await resume_run(db, pausada.id, "toolu_7", approved=False, deps=deps)


async def test_un_pendiente_vencido_no_se_puede_aprobar(
    db: AsyncSession, pausada: ChatSession, deps: AgentDeps, pedido: Order
):
    """Aprobar el martes algo propuesto el viernes anterior es ejecutar una
    acción con el contexto de otro momento: el pedido pudo haberse entregado."""
    aprobacion = await get_pending(db, pausada.id, "toolu_7")
    aprobacion.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await db.commit()

    with pytest.raises(ApprovalExpiredError):
        await resume_run(db, pausada.id, "toolu_7", approved=True, deps=deps)

    await db.refresh(pedido)
    assert pedido.status is OrderStatus.PENDING

    # Y queda marcado como vencido, que NO es lo mismo que rechazado: nadie dijo
    # que no, simplemente ya no es razonable ejecutarlo.
    await db.refresh(aprobacion)
    assert aprobacion.status is ApprovalStatus.EXPIRED


async def test_un_tool_use_id_inventado(db: AsyncSession, pausada: ChatSession, deps: AgentDeps):
    with pytest.raises(ApprovalNotFoundError):
        await resume_run(db, pausada.id, "toolu_inventado", approved=True, deps=deps)


async def test_no_se_puede_aprobar_en_una_sesion_activa(
    db: AsyncSession, chat: ChatSession, deps: AgentDeps
):
    """La sesión existe y es tuya, pero no está esperando nada."""
    with pytest.raises(ApprovalAlreadyDecidedError):
        await resume_run(db, chat.id, "toolu_7", approved=True, deps=deps)


# ---------------------------------------------------------------------------
# Varias tools sensibles en un mismo turno
# ---------------------------------------------------------------------------


async def test_decidir_una_de_dos_sigue_pausada(
    db: AsyncSession, chat: ChatSession, deps: AgentDeps, fake_model
):
    """Los `tool_result` van todos en UN mensaje, así que no se retoma hasta que
    estén todas resueltas. Decidir una devuelve las que faltan."""
    fake_model(
        response(
            tool_use("toolu_a", "cancel_order", order_id="o_1"),
            tool_use("toolu_b", "cancel_order", order_id="o_2"),
            stop_reason="tool_use",
        )
    )

    with pytest.raises(ApprovalRequired):
        await run_agent(db, chat.id, "cancelá los dos", deps)

    with pytest.raises(ApprovalRequired) as exc:
        await resume_run(db, chat.id, "toolu_a", approved=True, deps=deps)

    # La decisión de la primera SÍ quedó registrada.
    assert (await get_pending(db, chat.id, "toolu_a")).status is ApprovalStatus.APPROVED
    # Y la que falta es la otra.
    assert [a.tool_use_id for a in exc.value.aprobaciones] == ["toolu_b"]
    assert [a.tool_use_id for a in await pendientes_de(db, chat.id)] == ["toolu_b"]

    await db.refresh(chat)
    assert chat.status is SessionStatus.PENDING_APPROVAL


async def test_las_tools_inocentes_diferidas_se_ejecutan_al_retomar(
    db: AsyncSession, chat: ChatSession, deps: AgentDeps, pedido: Order, fake_model
):
    """La Fase 5 no ejecutó `calculate` porque el turno tenía una sensible.
    Al retomar corre, y su resultado va en el mismo mensaje que el otro."""
    fake_model(
        response(
            tool_use("toolu_1", "calculate", expression="42*2"),
            tool_use("toolu_7", "cancel_order", order_id="o_991"),
            stop_reason="tool_use",
        ),
        response(text("Son 84 y cancelé el pedido."), stop_reason="end_turn"),
    )

    with pytest.raises(ApprovalRequired):
        await run_agent(db, chat.id, "calculá 42*2 y cancelá el o_991", deps)

    await resume_run(db, chat.id, "toolu_7", approved=True, deps=deps)

    historial = await load_history(db, chat.id)
    resultados = _bloques(historial, "tool_result")

    # Los dos, y en UN SOLO mensaje `user`.
    assert {r["tool_use_id"] for r in resultados} == {"toolu_1", "toolu_7"}
    mensajes_con_resultados = [
        m for m in historial if any(b["type"] == "tool_result" for b in m["content"])
    ]
    assert len(mensajes_con_resultados) == 1


# ---------------------------------------------------------------------------
# El flujo completo, por HTTP
# ---------------------------------------------------------------------------


async def test_flujo_202_aprobar_respuesta(
    client: AsyncClient, db: AsyncSession, chat: ChatSession, pedido: Order, fake_model
):
    """La secuencia que un cliente real hace de punta a punta."""
    fake_model(
        response(tool_use("toolu_7", "cancel_order", order_id="o_991"), stop_reason="tool_use"),
        response(text("Listo, cancelé el pedido 991."), stop_reason="end_turn"),
    )

    primera = await client.post(
        f"/sessions/{chat.id}/messages",
        headers=CABECERA,
        json={"prompt": "cancelá el pedido o_991"},
    )
    assert primera.status_code == 202
    tool_use_id = primera.json()["pending"][0]["tool_use_id"]

    segunda = await client.post(
        f"/sessions/{chat.id}/approvals/{tool_use_id}",
        headers=CABECERA,
        json={"approved": True},
    )

    assert segunda.status_code == 200
    assert segunda.json()["answer"] == "Listo, cancelé el pedido 991."

    await db.refresh(pedido)
    assert pedido.status is OrderStatus.CANCELLED


async def test_otro_usuario_no_puede_aprobar(
    client: AsyncClient, db: AsyncSession, chat: ChatSession, pedido: Order, fake_model
):
    """404 y no 403: distinguirlos permitiría enumerar sesiones ajenas."""
    fake_model(
        response(tool_use("toolu_7", "cancel_order", order_id="o_991"), stop_reason="tool_use")
    )

    await client.post(
        f"/sessions/{chat.id}/messages", headers=CABECERA, json={"prompt": "cancelá el o_991"}
    )

    respuesta = await client.post(
        f"/sessions/{chat.id}/approvals/toolu_7",
        headers={"X-User-Id": "u_7"},
        json={"approved": True},
    )

    assert respuesta.status_code == 404
    await db.refresh(pedido)
    assert pedido.status is OrderStatus.PENDING


async def test_el_segundo_post_devuelve_409(
    client: AsyncClient, db: AsyncSession, chat: ChatSession, pedido: Order, fake_model
):
    """No 200 silencioso: un botón con doble click reportaría dos éxitos donde
    hubo una sola acción."""
    fake_model(
        response(tool_use("toolu_7", "cancel_order", order_id="o_991"), stop_reason="tool_use"),
        response(text("Listo."), stop_reason="end_turn"),
    )

    await client.post(
        f"/sessions/{chat.id}/messages", headers=CABECERA, json={"prompt": "cancelá el o_991"}
    )
    await client.post(
        f"/sessions/{chat.id}/approvals/toolu_7", headers=CABECERA, json={"approved": True}
    )

    repetido = await client.post(
        f"/sessions/{chat.id}/approvals/toolu_7", headers=CABECERA, json={"approved": True}
    )

    assert repetido.status_code == 409
