"""Fase 7 — que el tope corte ANTES de la llamada, no después.

El test que define la fase es `test_corta_antes_de_llamar_al_modelo`: verifica
que `messages.create` no se llamó ni una vez. Contar tokens después de gastarlos
sirve para la factura, no para evitarla.
"""

import pytest
from anthropic.types import Usage
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.budget import BudgetExceededError, costo_usd, marcar_agotada, verificar
from app.deps import AgentDeps
from app.models import ChatSession, SessionStatus
from app.agent import run_agent
from tests.conftest import response, text, tool_use

CABECERA = {"X-User-Id": "u_42"}


# ---------------------------------------------------------------------------
# La cuenta, sin base ni modelo
# ---------------------------------------------------------------------------


def test_verificar_deja_pasar_lo_que_entra():
    sesion = ChatSession(user_id="u_42", budget_tokens=1_000, input_tokens_used=200)

    verificar(sesion, estimado=700)  # 200 + 700 <= 1000


def test_verificar_corta_lo_que_no_entra():
    sesion = ChatSession(user_id="u_42", budget_tokens=1_000, input_tokens_used=200)

    with pytest.raises(BudgetExceededError) as exc:
        verificar(sesion, estimado=900)

    # Los números viajan con el error: un "sin presupuesto" a secas obliga a
    # adivinar si faltan 100 tokens o 100.000.
    assert exc.value.necesarios == 900
    assert exc.value.disponibles == 800


def test_el_gasto_en_vuelo_cuenta():
    """Lo que este turno ya consumió todavía no está en la fila.

    Sin este término, la vuelta 3 chequearía contra un contador que no se movió
    desde antes de la vuelta 1, y un solo turno podría pasarse del presupuesto
    entero sin que ningún chequeo lo note.
    """
    sesion = ChatSession(user_id="u_42", budget_tokens=1_000, input_tokens_used=0)

    # Solo, entra. Con 800 ya gastados en este mismo turno, no.
    verificar(sesion, estimado=500)
    with pytest.raises(BudgetExceededError):
        verificar(sesion, estimado=500, gastado_en_vuelo=800)


def test_costo_en_dolares():
    """Entrada y salida se convierten por separado: cuestan distinto.

    Es la razón por la que la tabla lleva dos contadores. Uno solo no se puede
    convertir a plata sin inventar un promedio.
    """
    # 1M de entrada a $1 + 1M de salida a $5.
    assert costo_usd(Usage(input_tokens=1_000_000, output_tokens=1_000_000)) == 6.0
    # Y la asimetría se ve: el mismo millón cuesta 5 veces más si lo generó él.
    assert costo_usd(Usage(input_tokens=1_000_000, output_tokens=0)) == 1.0
    assert costo_usd(Usage(input_tokens=0, output_tokens=1_000_000)) == 5.0


# ---------------------------------------------------------------------------
# El loop
# ---------------------------------------------------------------------------


async def test_corta_antes_de_llamar_al_modelo(
    db: AsyncSession, chat: ChatSession, deps: AgentDeps, fake_model
):
    """EL test de la fase.

    Con el presupuesto agotado, `messages.create` no se llama NI UNA VEZ. Si el
    chequeo estuviera después de la llamada, el assert de abajo daría 1 — y el
    tope no serviría para nada, porque el gasto ya habría ocurrido.
    """
    fake = fake_model(response(text("hola")), estimado=99_999)

    with pytest.raises(BudgetExceededError):
        await run_agent(db, chat.id, "hola", deps)

    assert fake.messages.create.call_count == 0
    # Y sí se preguntó cuánto iba a costar, que es gratis. Más de una vez,
    # porque antes de rechazar el loop intenta recortar el contexto (Fase 8) y
    # vuelve a medir después de cada intento.
    assert fake.messages.count_tokens.call_count >= 1


async def test_la_estimacion_incluye_las_tools(
    db: AsyncSession, chat: ChatSession, deps: AgentDeps, fake_model
):
    """`count_tokens` tiene que recibir lo MISMO que `create`.

    Las definiciones de tools son tokens de entrada en cada vuelta. Dejarlas
    afuera de la cuenta subestima siempre, y subestimar un límite es no tener
    límite.
    """
    fake = fake_model(response(text("hola")))

    await run_agent(db, chat.id, "hola", deps)

    argumentos_cuenta = fake.messages.count_tokens.call_args.kwargs
    argumentos_request = fake.messages.create.call_args.kwargs

    assert argumentos_cuenta["tools"] == argumentos_request["tools"]
    assert argumentos_cuenta["messages"] == argumentos_request["messages"]
    assert argumentos_cuenta["model"] == argumentos_request["model"]


async def test_el_gasto_del_turno_abortado_se_cobra(
    db: AsyncSession, chat: ChatSession, deps: AgentDeps, fake_model
):
    """Un turno que se pasa en la vuelta 2 no puede salir gratis.

    El modelo ya trabajó una vuelta. Como el historial no se guarda, sin este
    cobro explícito ese gasto no lo registraría nadie — y es justamente el caso
    en el que más se gasta.
    """
    # Presupuesto que alcanza para la primera vuelta y no para la segunda.
    chat.budget_tokens = 1_000
    await db.commit()

    fake_model(
        response(
            tool_use("toolu_1", "calculate", expression="2+2"),
            stop_reason="tool_use",
            tokens=(400, 50),
        ),
        response(text("son 4")),
        estimado=900,
    )

    with pytest.raises(BudgetExceededError):
        await run_agent(db, chat.id, "cuánto es 2+2", deps)

    await db.refresh(chat)
    assert chat.input_tokens_used == 400
    assert chat.output_tokens_used == 50


async def test_la_sesion_queda_agotada(
    db: AsyncSession, chat: ChatSession, deps: AgentDeps, fake_model
):
    """`exhausted` no es un error transitorio: reintentar no lo arregla."""
    fake_model(response(text("hola")), estimado=99_999)

    with pytest.raises(BudgetExceededError):
        await run_agent(db, chat.id, "hola", deps)

    await db.refresh(chat)
    assert chat.status is SessionStatus.EXHAUSTED


async def test_un_turno_normal_no_toca_el_presupuesto(
    db: AsyncSession, chat: ChatSession, deps: AgentDeps, fake_model
):
    """La Fase 7 no puede romper la 2."""
    fake_model(response(text("hola"), tokens=(30, 8)))

    resultado = await run_agent(db, chat.id, "hola", deps)

    assert resultado.text == "hola"
    await db.refresh(chat)
    assert chat.status is SessionStatus.ACTIVE
    assert chat.input_tokens_used == 30


# ---------------------------------------------------------------------------
# La capa HTTP
# ---------------------------------------------------------------------------


async def test_402_con_los_numeros(
    client: AsyncClient, db: AsyncSession, chat: ChatSession, fake_model
):
    """402 Payment Required: el request es válido, el servicio anda, y no se
    atiende por cuota.

    429 diría "vas muy rápido, esperá" y acá esperar no sirve. 403 diría "no
    tenés permiso", y permiso hay.
    """
    fake_model(response(text("hola")), estimado=99_999)

    respuesta = await client.post(
        f"/sessions/{chat.id}/messages", headers=CABECERA, json={"prompt": "hola"}
    )

    assert respuesta.status_code == 402
    cuerpo = respuesta.json()
    assert cuerpo["tokens_necesarios"] == 99_999
    assert cuerpo["tokens_disponibles"] == 10_000


async def test_una_sesion_agotada_no_llega_ni_a_estimar(
    client: AsyncClient, db: AsyncSession, chat: ChatSession, fake_model
):
    """El chequeo más barato para el caso de rechazo más común."""
    chat.status = SessionStatus.EXHAUSTED
    await db.commit()

    fake = fake_model(response(text("hola")))

    respuesta = await client.post(
        f"/sessions/{chat.id}/messages", headers=CABECERA, json={"prompt": "hola"}
    )

    assert respuesta.status_code == 402
    assert fake.messages.count_tokens.call_count == 0


async def test_budget_remaining_en_la_respuesta(
    client: AsyncClient, db: AsyncSession, chat: ChatSession, fake_model
):
    """Se calcula, no se guarda: un contador derivado que se persiste es uno que
    algún día va a discrepar de aquello de lo que deriva."""
    fake_model(response(text("hola"), tokens=(250, 10)))

    respuesta = await client.post(
        f"/sessions/{chat.id}/messages", headers=CABECERA, json={"prompt": "hola"}
    )

    assert respuesta.json()["budget_remaining"] == 10_000 - 250


async def test_marcar_agotada_es_idempotente_en_el_estado(
    db: AsyncSession, chat: ChatSession
):
    """Llamarla dos veces suma dos veces el gasto pero no rompe el estado.

    Es un detalle menor y vale tenerlo presente: el estado es idempotente, el
    contador no. Por eso se llama en un solo lugar.
    """
    await marcar_agotada(db, chat.id, input_tokens=10, output_tokens=1)
    await marcar_agotada(db, chat.id, input_tokens=10, output_tokens=1)

    await db.refresh(chat)
    assert chat.status is SessionStatus.EXHAUSTED
    assert chat.input_tokens_used == 20
