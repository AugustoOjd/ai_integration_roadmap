"""Datos de prueba para las tools con dueño.

    uv run alembic upgrade head      # el esquema tiene que existir antes
    uv run python -m scripts.seed_orders

Crea pedidos para DOS usuarios a propósito. Con un solo usuario, una tool que
ignora el filtro por dueño se vería bien: hace falta tener datos ajenos para que
"no los devolvió" signifique algo.
"""

from sqlalchemy import delete, select

from app.db import SessionFactory, engine
from app.models import Order, OrderStatus

PEDIDOS = [
    # El usuario con el que vas a probar.
    ("u_42", "Teclado mecánico", 12_990, False, OrderStatus.SHIPPED),
    ("u_42", "Monitor 27 pulgadas", 34_500, True, OrderStatus.SHIPPED),
    ("u_42", "Cable USB-C", 1_290, False, OrderStatus.PENDING),
    ("u_42", "Silla ergonómica", 78_000, True, OrderStatus.PENDING),
    # El OTRO usuario. Estos no tienen que aparecer nunca consultando como u_42,
    # ni siquiera si se lo pedís al modelo explícitamente.
    ("u_7", "Notebook", 250_000, False, OrderStatus.SHIPPED),
    ("u_7", "Mouse inalámbrico", 4_500, False, OrderStatus.PENDING),
]


def main() -> None:
    with SessionFactory() as db:
        # Idempotente: borra lo sembrado antes y vuelve a sembrar. Un seed que
        # duplica datos cada vez que lo corrés es un seed que vas a dejar de correr.
        db.execute(delete(Order).where(Order.user_id.in_(["u_42", "u_7"])))

        db.add_all(
            Order(
                user_id=user_id,
                item=item,
                amount_cents=monto,
                has_discount=descuento,
                status=estado,
            )
            for user_id, item, monto, descuento, estado in PEDIDOS
        )
        db.commit()

        filas = db.execute(select(Order).order_by(Order.user_id)).scalars().all()
        for pedido in filas:
            print(
                f"  {pedido.user_id}  {pedido.id}  {pedido.item:<22} "
                f"${pedido.amount_cents / 100:>9,.2f}  {pedido.status.value}"
            )

    print(f"\n✓ {len(PEDIDOS)} pedidos sembrados (u_42 y u_7)")
    engine.dispose()


if __name__ == "__main__":
    main()
