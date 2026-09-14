"""Fase 3 — las tools con dueño.

Dos tools que parecen casi iguales y enseñan cosas opuestas:

    get_my_orders(ctx)             → input_schema VACÍO
    get_order(ctx, order_id)       → input_schema con un campo

La diferencia no es de estilo. `get_my_orders` no tiene ni un argumento que el
modelo pueda elegir: "de quién" sale del contexto autenticado y punto.
`get_order` sí recibe algo del modelo —cuál pedido— pero ese dato no define
permisos, sólo selecciona. Y aun así la query filtra por `ctx.deps.user_id`,
porque un id de pedido ajeno es adivinable y "seleccionar" no puede convertirse
en "acceder".

La regla, en dos líneas:

    lo que define PERMISOS   → contexto, nunca en el schema
    lo que define QUÉ COSA   → puede ir en el schema, pero se valida contra el
                               contexto igual
"""

from typing import Annotated, Any

from pydantic import Field
from sqlalchemy import select

from app.deps import AgentDeps, RunContext
from app.models import Order, OrderStatus
from app.tools.registry import registry


def _a_dict(order: Order) -> dict[str, Any]:
    """Cómo ve el modelo un pedido.

    Es una proyección deliberada, no un volcado de la fila. Lo que devuelve una
    tool entra al contexto del modelo, y de ahí puede terminar repetido en la
    respuesta al usuario — así que se elige campo por campo.

    Dos decisiones concretas:

      - El `user_id` NO va. El modelo no lo necesita para nada (ya sabe de quién
        son: son los del usuario que preguntó), y meterlo en el contexto es
        invitarlo a razonar sobre ids de usuario, que es justo lo que la fase
        intenta sacar de su alcance.
      - El monto se convierte a la unidad que un humano espera leer. Mandarle
        `amount_cents` al modelo es pedirle que divida por 100 y espere que no
        se equivoque.
    """
    return {
        "order_id": order.id,
        "item": order.item,
        "amount": round(order.amount_cents / 100, 2),
        "currency": "USD",
        "has_discount": order.has_discount,
        "status": order.status.value,
        "created_at": order.created_at.date().isoformat(),
    }


@registry.tool
async def get_my_orders(ctx: RunContext[AgentDeps]) -> list[dict[str, Any]]:
    """Lista los pedidos del usuario actual, del más nuevo al más viejo.

    Usala cuando el usuario pregunte por sus pedidos, sus compras o cuánto
    gastó. No recibe argumentos: siempre devuelve los del usuario que está
    conversando, nunca los de otro.
    """
    # Este docstring es PROMPT: es literalmente lo que el modelo lee para
    # decidir si llamar a esta tool. La última frase está ahí a propósito —
    # no como control de seguridad (el control es que `user_id` no exista en el
    # schema), sino para que el modelo no pierda vueltas intentando pasar un
    # argumento que no puede pasar.
    consulta = (
        select(Order)
        # De acá sale el "de quién": del contexto, que vino del token. El modelo
        # no participó de esta decisión y no puede influirla.
        .where(Order.user_id == ctx.deps.user_id)
        .order_by(Order.created_at.desc())
        # Tope duro. Todo lo que devuelve una tool se paga en tokens, en CADA
        # vuelta del loop y en cada turno futuro de la sesión, porque queda en
        # el historial. Un usuario con 4000 pedidos no puede hacer que una sola
        # pregunta cueste medio presupuesto.
        .limit(50)
    )
    pedidos = (await ctx.deps.db.execute(consulta)).scalars().all()
    return [_a_dict(pedido) for pedido in pedidos]


@registry.tool
async def get_order(
    ctx: RunContext[AgentDeps],
    order_id: Annotated[str, Field(description="El id del pedido, con el formato o_xxxx.")],
) -> dict[str, Any]:
    """Trae el detalle de UN pedido del usuario actual, por su id.

    Usala cuando el usuario mencione un pedido puntual. Si el pedido no existe
    o no es suyo, devuelve un error.
    """
    consulta = select(Order).where(
        Order.id == order_id,
        # El filtro por dueño va en la MISMA query, no en un `if` después.
        #
        # No es paranoia: `order_id` lo eligió el modelo, y el modelo lo sacó
        # del texto del usuario. Que el parámetro sea legítimo (seleccionar un
        # pedido es su función) no lo vuelve confiable.
        Order.user_id == ctx.deps.user_id,
    )
    pedido = (await ctx.deps.db.execute(consulta)).scalar_one_or_none()

    if pedido is None:
        # Mismo mensaje para "no existe" y para "es de otro", a propósito.
        # Distinguirlos convertiría a la tool en un oráculo: probando ids, el
        # modelo —o quien lo esté guiando— podría averiguar qué pedidos existen
        # aunque no pueda verlos. Es la misma razón por la que un login no dice
        # "ese usuario no existe" en vez de "credenciales inválidas".
        #
        # Y va como valor de retorno, no como excepción: el modelo tiene que
        # poder leerlo y reaccionar ("no encontré ese pedido, ¿me confirmás el
        # número?").
        return {"error": f"no se encontró el pedido {order_id}"}

    return _a_dict(pedido)


@registry.tool
async def cancel_order(
    ctx: RunContext[AgentDeps],
    order_id: Annotated[str, Field(description="El id del pedido a cancelar, formato o_xxxx.")],
) -> dict[str, Any]:
    """Cancela un pedido del usuario actual. Sólo funciona si todavía no se envió.

    Usala cuando el usuario pida explícitamente cancelar un pedido. Confirmá con
    él cuál es antes de llamarla.
    """
    # -------------------------------------------------- TOOL SENSIBLE (Fase 5)
    #
    # Esta función no se ejecuta cuando el modelo la pide. El loop la ve en
    # `policy.REQUIEREN_APROBACION`, se frena, y persiste el pedido: recién
    # cuando un humano dice que sí, este código corre.
    #
    # Y fijate que la función no sabe nada de eso. No consulta la política, no
    # pregunta si fue aprobada, no tiene un flag `approved=True`. La aprobación
    # es responsabilidad del loop, no de la tool — si estuviera acá adentro,
    # cada tool nueva tendría que acordarse de implementarla, y la que se
    # olvidara sería el agujero.
    consulta = select(Order).where(
        Order.id == order_id,
        Order.user_id == ctx.deps.user_id,
    )
    pedido = (await ctx.deps.db.execute(consulta)).scalar_one_or_none()

    if pedido is None:
        return {"error": f"no se encontró el pedido {order_id}"}

    if pedido.status is not OrderStatus.PENDING:
        # Regla de negocio, no de seguridad: un pedido enviado no se cancela, se
        # devuelve. Va como valor de retorno para que el modelo pueda
        # explicárselo al usuario en vez de quedarse mudo.
        return {
            "error": f"el pedido {order_id} está en estado {pedido.status.value} "
            f"y sólo se pueden cancelar los pendientes"
        }

    pedido.status = OrderStatus.CANCELLED
    # Sin `commit` acá: la tool participa de la transacción de quien la llamó.
    # Un `commit` adentro de una tool le arrebataría al loop el control sobre
    # qué se guarda junto con qué — y en la Fase 6 lo que se guarda junto es
    # justamente "la cancelación Y el tool_result que la registra".
    await ctx.deps.db.flush()

    return {"order_id": pedido.id, "status": pedido.status.value, "cancelled": True}
