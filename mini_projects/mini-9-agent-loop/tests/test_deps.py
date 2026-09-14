"""Fase 3 — que el modelo no pueda elegir de quién son los datos.

Dos niveles de test, y hacen falta los dos:

  1. El CONTRATO: que `user_id` no exista en ningún `input_schema`. Es el test
     que previene el agujero, y corre sin base y sin modelo.
  2. El COMPORTAMIENTO: que la tool filtre por el contexto aunque le insistan.

El primero es el que más vale. El segundo verifica que la implementación de hoy
está bien; el primero impide que alguien la rompa mañana agregando un parámetro
"sólo para este caso".
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import AgentDeps, RunContext
from app.models import Order, OrderStatus
from app.tools import registry
from app.tools.orders import get_my_orders, get_order


@pytest.fixture
async def pedidos(db: AsyncSession) -> None:
    """Pedidos de DOS usuarios.

    Con un solo usuario, una tool que ignora el filtro por dueño pasaría todos
    los tests: hay que tener datos ajenos para que "no los devolvió" signifique
    algo.
    """
    db.add_all(
        [
            Order(id="o_mio_1", user_id="u_42", item="Teclado", amount_cents=12_990),
            Order(
                id="o_mio_2",
                user_id="u_42",
                item="Monitor",
                amount_cents=34_500,
                has_discount=True,
                status=OrderStatus.SHIPPED,
            ),
            Order(id="o_ajeno", user_id="u_7", item="Notebook", amount_cents=250_000),
        ]
    )
    await db.commit()


@pytest.fixture
def ctx(db: AsyncSession) -> RunContext[AgentDeps]:
    """El contexto de u_42. Simula lo que la ruta arma desde el token."""
    return RunContext(deps=AgentDeps(user_id="u_42", session_id="s_test", db=db))


# ---------------------------------------------------------------------------
# 1. El contrato: qué ve el modelo
# ---------------------------------------------------------------------------


def test_ninguna_tool_expone_identidad_en_su_schema():
    """EL test de la fase. Corre sin base, sin modelo y sin red.

    Si algún día alguien agrega `user_id: str` a una tool "porque era más
    cómodo", esto falla en CI antes de que el agujero llegue a producción. Es
    una regla de arquitectura convertida en assert.
    """
    prohibidos = {"user_id", "tenant_id", "account_id", "owner_id", "customer_id"}

    for tool in registry.to_params():
        campos = set(tool["input_schema"].get("properties", {}))
        assert not (campos & prohibidos), (
            f"la tool {tool['name']!r} expone identidad en su schema: {campos & prohibidos}. "
            "Lo que define permisos va por RunContext, nunca en el input_schema."
        )


def test_el_contexto_no_aparece_en_el_schema():
    """`get_my_orders(ctx)` tiene un parámetro y un schema vacío."""
    schema = next(t for t in registry.to_params() if t["name"] == "get_my_orders")["input_schema"]

    assert schema.get("properties", {}) == {}
    # Sin `required`, o vacío: el modelo puede llamarla con `{}`.
    assert not schema.get("required")


def test_una_tool_puede_recibir_datos_que_no_definen_permisos():
    """`get_order(ctx, order_id)` SÍ tiene un campo: cuál pedido.

    La distinción de la fase: `order_id` selecciona, no autoriza. Puede venir
    del modelo — pero la query filtra igual por el dueño del contexto.
    """
    schema = next(t for t in registry.to_params() if t["name"] == "get_order")["input_schema"]

    assert set(schema["properties"]) == {"order_id"}


def test_el_registry_rechaza_un_contexto_fuera_de_la_primera_posicion():
    """Falla al importar, no en la primera llamada del modelo a esa tool."""
    from app.tools.registry import ToolRegistry

    otro = ToolRegistry()

    with pytest.raises(TypeError, match="primer parámetro"):

        @otro.tool
        def mal(expression: str, ctx: RunContext[AgentDeps]) -> str:
            """Una tool con el contexto en el lugar equivocado."""
            return expression


# ---------------------------------------------------------------------------
# 2. El comportamiento: qué devuelve la tool
# ---------------------------------------------------------------------------


async def test_get_my_orders_usa_el_usuario_del_contexto(ctx, pedidos):
    """Los dos pedidos de u_42, y ninguno de u_7."""
    resultado = await get_my_orders(ctx)

    assert {p["order_id"] for p in resultado} == {"o_mio_1", "o_mio_2"}


async def test_la_proyeccion_no_le_muestra_el_user_id_al_modelo(ctx, pedidos):
    """Lo que devuelve una tool entra al contexto del modelo: se elige campo a campo."""
    resultado = await get_my_orders(ctx)

    assert "user_id" not in resultado[0]
    # El monto va en la unidad que un humano lee, no en centavos.
    assert {p["amount"] for p in resultado} == {129.90, 345.00}


async def test_get_order_ajeno_no_devuelve_nada(ctx, pedidos):
    """El id existe y es válido. No importa: no es del usuario del contexto."""
    ajeno = await get_order(ctx, order_id="o_ajeno")
    inexistente = await get_order(ctx, order_id="o_no_existe")

    # Ni un solo dato del pedido ajeno: ni el item, ni el monto, ni el dueño.
    assert set(ajeno) == {"error"}

    # Y la MISMA respuesta que para un id que no existe. Que el texto repita el
    # id pedido no filtra nada —lo mandó quien preguntó—; lo que no puede pasar
    # es que una respuesta diga "existe pero no es tuyo" y la otra "no existe",
    # porque eso convierte a la tool en un oráculo para enumerar pedidos.
    assert ajeno["error"].replace("o_ajeno", "X") == inexistente["error"].replace(
        "o_no_existe", "X"
    )


async def test_un_prompt_que_pide_datos_ajenos_no_llega_a_ningun_lado(ctx, pedidos):
    """El escenario de ataque, sin modelo en el medio.

    Un usuario escribe "mostrame los pedidos del usuario 7". El modelo, en el
    mejor de los casos para el atacante, intenta pasar ese dato — y ni siquiera
    tiene por dónde: no hay campo. Lo simulamos llamando a `execute` con el
    input que el modelo mandaría.
    """
    with pytest.raises(Exception) as exc:
        await registry.execute("get_my_orders", {"user_id": "u_7"}, ctx)

    # `extra="forbid"` en el modelo de input: un campo inventado es un error
    # explícito, no un valor que se ignora en silencio.
    assert "user_id" in str(exc.value)


async def test_execute_inyecta_el_contexto(ctx, pedidos):
    """El camino completo: como lo llama el loop."""
    salida = await registry.execute("get_my_orders", {}, ctx)

    # `execute` devuelve string (es lo que pide `tool_result`), serializado como
    # JSON para que el modelo lo lea sin ambigüedad.
    assert "o_mio_1" in salida
    assert "o_ajeno" not in salida


async def test_execute_sin_contexto_para_una_tool_que_lo_pide():
    """Bug de programación: revienta fuerte y acá.

    La alternativa —ejecutarla con un contexto vacío— sería consultar datos sin
    saber de quién son, que es exactamente lo que la fase evita.
    """
    with pytest.raises(RuntimeError, match="necesita contexto"):
        await registry.execute("get_my_orders", {})


async def test_una_tool_sin_contexto_sigue_funcionando(ctx):
    """El registry no rompió las tools del mini 8.

    Devuelve "84" y no "84.0": el evaluador AST hace `42 * 2` con enteros, y
    `json.dumps` de un int no le agrega decimales. Que la anotación de retorno
    diga `float` no convierte nada — en Python las anotaciones no coaccionan.
    """
    assert await registry.execute("calculate", {"expression": "42 * 2"}, ctx) == "84"
