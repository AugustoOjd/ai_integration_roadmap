"""Datos de prueba para las tools de la Fase 3.

    uv run python -m scripts.seed_orders

Crea pedidos para DOS usuarios a propósito. Con un solo usuario, una tool que
ignora el filtro por dueño pasaría todos los tests: hay que tener datos ajenos
para que "no los devolvió" signifique algo.
"""

import asyncio

from sqlalchemy import delete, select

from app.db import SessionFactory, create_schema, engine
from app.models import Order, OrderStatus

PEDIDOS = [
    # El usuario con el que vas a probar.
    ("u_42", "Teclado mecánico", 12_990, False, OrderStatus.SHIPPED),
    ("u_42", "Monitor 27 pulgadas", 34_500, True, OrderStatus.SHIPPED),
    ("u_42", "Cable USB-C", 1_290, False, OrderStatus.PENDING),
    ("u_42", "Silla ergonómica", 78_000, True, OrderStatus.PENDING),
    # El OTRO usuario. Estos pedidos no tienen que aparecer nunca cuando
    # consultás como u_42, ni siquiera si se lo pedís al modelo explícitamente.
    ("u_7", "Notebook", 250_000, False, OrderStatus.SHIPPED),
    ("u_7", "Mouse inalámbrico", 4_500, False, OrderStatus.PENDING),
]


async def main() -> None:
    await create_schema()

    async with SessionFactory() as db:
        # Idempotente: borra lo sembrado antes y vuelve a sembrar. Un script de
        # seed que duplica datos cada vez que lo corrés es un script que vas a
        # dejar de correr.
        await db.execute(delete(Order).where(Order.user_id.in_(["u_42", "u_7"])))

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
        await db.commit()

        filas = (await db.execute(select(Order).order_by(Order.user_id))).scalars().all()
        for pedido in filas:
            print(f"  {pedido.user_id}  {pedido.id}  {pedido.item:<22} ${pedido.amount_cents / 100:>9,.2f}")

    print(f"\n✓ {len(PEDIDOS)} pedidos sembrados (u_42 y u_7)")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
