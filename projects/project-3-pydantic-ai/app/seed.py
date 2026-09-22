"""Recrea el esquema y lo llena con datos falsos.

    uv run python -m app.seed

Destructivo: tira las tablas y las vuelve a crear. Los ids de cliente son fijos
y legibles (`cus_ana`) porque los vas a tipear a mano para elegir de quién es la
sesión.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.core.db import SessionFactory, engine
from app.core.models import Base, Customer, Order, OrderStatus

# Fijo, no datetime.now(): con una base de referencia estable las fechas del seed
# son siempre las mismas relativas entre sí.
_HOY = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)


def _hace(dias: int) -> datetime:
    return _HOY - timedelta(days=dias)


CUSTOMERS = [
    Customer(id="cus_ana", name="Ana Suárez", email="ana@example.com"),
    Customer(id="cus_bruno", name="Bruno Klein", email="bruno@example.com"),
    Customer(id="cus_carla", name="Carla Ndiaye", email="carla@example.com"),
]

ORDERS = [
    # Ana: un paquete que dice "entregado" pero ella no lo recibió, y un cobro
    # duplicado. Es el caso del prompt de ejemplo del README.
    Order(id="ord_ana_1", customer_id="cus_ana", description="Auriculares BT",
          total=Decimal("89.90"), status=OrderStatus.DELIVERED, placed_at=_hace(12)),
    Order(id="ord_ana_2", customer_id="cus_ana", description="Auriculares BT",
          total=Decimal("89.90"), status=OrderStatus.DELIVERED, placed_at=_hace(12)),
    Order(id="ord_ana_3", customer_id="cus_ana", description="Funda de silicona",
          total=Decimal("12.50"), status=OrderStatus.SHIPPED, placed_at=_hace(3)),

    # Bruno: una orden cara y sin despachar. Sirve para probar un reembolso que
    # se pasa del total.
    Order(id="ord_bruno_1", customer_id="cus_bruno", description="Monitor 27\"",
          total=Decimal("340.00"), status=OrderStatus.PENDING, placed_at=_hace(1)),
    Order(id="ord_bruno_2", customer_id="cus_bruno", description="Cable HDMI",
          total=Decimal("9.99"), status=OrderStatus.DELIVERED, placed_at=_hace(45)),

    # Carla: una cancelada. Reembolsar algo cancelado no debería pasar.
    Order(id="ord_carla_1", customer_id="cus_carla", description="Teclado mecánico",
          total=Decimal("120.00"), status=OrderStatus.CANCELLED, placed_at=_hace(8)),
    Order(id="ord_carla_2", customer_id="cus_carla", description="Mousepad XL",
          total=Decimal("18.00"), status=OrderStatus.DELIVERED, placed_at=_hace(30)),
]


async def main() -> None:
    # run_sync: create_all/drop_all son sincrónicos y corren sobre la conexión
    # async a través del greenlet que expone SQLAlchemy.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with SessionFactory() as session:
        # Los clientes primero y con flush: las órdenes tienen FK contra ellos.
        session.add_all(CUSTOMERS)
        await session.flush()
        session.add_all(ORDERS)
        await session.commit()

    print(f"{len(CUSTOMERS)} clientes, {len(ORDERS)} órdenes.")
    for c in CUSTOMERS:
        n = sum(1 for o in ORDERS if o.customer_id == c.id)
        print(f"  {c.id:<12} {c.name:<16} {n} órdenes")

    # Sin esto el proceso termina con conexiones abiertas y asyncio se queja.
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
