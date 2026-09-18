"""Las tools con dueño.

Dos tools casi iguales que enseñan cosas opuestas:

    get_my_orders(ctx)             → input_schema VACÍO
    get_order(ctx, order_id)       → input_schema con un campo

`get_my_orders` no tiene un solo argumento que el modelo pueda elegir: "de quién"
sale del contexto autenticado. `get_order` sí recibe algo del modelo —cuál
pedido— pero ese dato no define permisos, sólo selecciona. Y aun así la query
filtra por `ctx.deps.user_id`, porque un id de pedido ajeno es adivinable y
"seleccionar" no puede convertirse en "acceder".

    lo que define PERMISOS   → contexto, nunca en el schema
    lo que define QUÉ COSA   → puede ir en el schema, pero se valida contra el
                               contexto igual
"""

from typing import Annotated, Any

from pydantic import Field
from sqlalchemy import select

from app.agent.deps import AgentDeps, RunContext
from app.core.models import Order, OrderStatus
from app.tools.registry import registry


def _a_dict(order: Order) -> dict[str, Any]:
    """Cómo ve el modelo un pedido: una proyección elegida, no la fila entera.

    El user_id no va: el modelo no lo necesita (ya sabe de quién son) y meterlo
    en el contexto lo invita a razonar sobre ids de usuario.

    El monto se convierte a la unidad que un humano lee. Mandarle `amount_cents`
    es pedirle que divida por 100 y esperar que no se equivoque.
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
def get_my_orders(ctx: RunContext[AgentDeps]) -> list[dict[str, Any]]:
    """Lista los pedidos del usuario actual, del más nuevo al más viejo.

    Usala cuando el usuario pregunte por sus pedidos, sus compras o cuánto gastó.
    No recibe argumentos: siempre devuelve los del usuario que está conversando,
    nunca los de otro.
    """
    # El docstring de arriba es prompt: es lo que el modelo lee para decidir si
    # llamar a esta tool. La última frase no es un control de seguridad (el
    # control es que user_id no exista en el schema) sino para que no pierda
    # vueltas intentando pasar un argumento que no puede pasar.
    consulta = (
        select(Order)
        # De acá sale el "de quién": del contexto, que vino del token. El modelo
        # no participó de esta decisión.
        .where(Order.user_id == ctx.deps.user_id)
        .order_by(Order.created_at.desc())
        # Tope duro: lo que devuelve una tool se paga en tokens en cada vuelta del
        # loop y en cada turno futuro, porque queda en el historial.
        .limit(50)
    )
    pedidos = ctx.deps.db.execute(consulta).scalars().all()
    return [_a_dict(pedido) for pedido in pedidos]


@registry.tool
def get_order(
    ctx: RunContext[AgentDeps],
    order_id: Annotated[str, Field(description="El id del pedido, con el formato o_xxxx.")],
) -> dict[str, Any]:
    """Trae el detalle de UN pedido del usuario actual, por su id.

    Usala cuando el usuario mencione un pedido puntual. Si el pedido no existe o
    no es suyo, devuelve un error.
    """
    consulta = select(Order).where(
        Order.id == order_id,
        # El filtro por dueño va en la misma query, no en un `if` después:
        # order_id lo eligió el modelo a partir del texto del usuario, y que el
        # parámetro sea legítimo no lo vuelve confiable.
        Order.user_id == ctx.deps.user_id,
    )
    pedido = ctx.deps.db.execute(consulta).scalar_one_or_none()

    if pedido is None:
        # Mismo mensaje para "no existe" y para "es de otro": distinguirlos
        # convertiría la tool en un oráculo para averiguar qué pedidos existen.
        # Es la razón por la que un login dice "credenciales inválidas" y no "ese
        # usuario no existe".
        #
        # Y va como valor de retorno, no como excepción, para que el modelo pueda
        # reaccionar ("no encontré ese pedido, ¿me confirmás el número?").
        return {"error": f"no se encontró el pedido {order_id}"}

    return _a_dict(pedido)


@registry.tool
def cancel_order(
    ctx: RunContext[AgentDeps],
    order_id: Annotated[str, Field(description="El id del pedido a cancelar, formato o_xxxx.")],
) -> dict[str, Any]:
    """Cancela un pedido del usuario actual. Sólo funciona si todavía no se envió.

    Usala cuando el usuario pida explícitamente cancelar un pedido. Confirmá con
    él cuál es antes de llamarla.
    """
    # Tool sensible: el loop la ve en policy.REQUIEREN_APROBACION, se frena y
    # persiste el pedido. Este código corre recién cuando un humano dice que sí.
    #
    # La función no sabe nada de eso: no consulta la política ni tiene un flag
    # `approved`. Si la aprobación viviera acá adentro, cada tool nueva tendría
    # que acordarse de implementarla y la que se olvidara sería el agujero.
    consulta = select(Order).where(
        Order.id == order_id,
        Order.user_id == ctx.deps.user_id,
    )
    pedido = ctx.deps.db.execute(consulta).scalar_one_or_none()

    if pedido is None:
        return {"error": f"no se encontró el pedido {order_id}"}

    if pedido.status is not OrderStatus.PENDING:
        # Regla de negocio, no de seguridad: un pedido enviado no se cancela, se
        # devuelve. Va como retorno para que el modelo se lo explique al usuario.
        return {
            "error": f"el pedido {order_id} está en estado {pedido.status.value} "
            f"y sólo se pueden cancelar los pendientes"
        }

    pedido.status = OrderStatus.CANCELLED
    # Sin commit: la tool participa de la transacción de quien la llamó. Un
    # commit acá le arrebataría al loop el control sobre qué se guarda junto con
    # qué — y lo que se guarda junto es la cancelación y el tool_result que la
    # registra.
    ctx.deps.db.flush()

    return {"order_id": pedido.id, "status": pedido.status.value, "cancelled": True}
