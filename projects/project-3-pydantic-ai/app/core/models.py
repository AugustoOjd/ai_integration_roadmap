"""Las tablas.

    customers       quién pregunta
    orders          sobre qué pregunta
    conversations   el historial, en la representación del framework
"""

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Numeric,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Raíz de los modelos. Vive acá para que importarlos no arrastre un engine."""


def _new_id(prefix: str) -> str:
    """Id con prefijo legible, estilo Stripe: `cus_3f9a…`, `ord_8b2c…`.

    Un autoincremental delataría cuántas filas hay y dejaría probar con el de al
    lado.
    """
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class OrderStatus(StrEnum):
    PENDING = "pending"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: _new_id("cus")
    )
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), unique=True)

    orders: Mapped[list["Order"]] = relationship(
        back_populates="customer",
        # Sin esto, tocar customer.orders en código async dispara un SELECT
        # implícito y SQLAlchemy levanta MissingGreenlet.
        lazy="raise",
    )


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: _new_id("ord")
    )
    customer_id: Mapped[str] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE")
    )

    description: Mapped[str] = mapped_column(String(200))

    # Numeric, no Float: la plata en binario acumula error y esto se compara
    # contra el monto que pide el modelo. psycopg lo devuelve como Decimal.
    total: Mapped[Decimal] = mapped_column(Numeric(10, 2))

    # native_enum=False: un VARCHAR con CHECK en vez de un tipo ENUM de Postgres,
    # que necesitaría un ALTER TYPE para agregar un valor.
    status: Mapped[OrderStatus] = mapped_column(
        SAEnum(OrderStatus, native_enum=False, length=16),
        default=OrderStatus.PENDING,
    )

    # Acumulado: una orden puede reembolsarse en partes. Lo que queda es
    # total - refunded_total, y ese es el techo que la tool hace cumplir.
    refunded_total: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), server_default=text("0")
    )

    placed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    customer: Mapped[Customer] = relationship(back_populates="orders", lazy="raise")

    __table_args__ = (
        # El acceso de siempre es "las N órdenes más recientes de este cliente".
        Index("ix_orders_customer_placed", "customer_id", text("placed_at DESC")),
    )


class Conversation(Base):
    """Un hilo: quién es, y el historial tal como lo serializa el framework.

    `messages` NO son los bloques de la Messages API de Anthropic: es la
    representación propia de Pydantic AI, la misma para cualquier provider. Eso
    es lo que permite continuar un hilo con otro modelo — y lo que impide
    reproducir la llamada original contra la API cruda desde esta tabla.
    """

    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: _new_id("conv")
    )
    customer_id: Mapped[str] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE")
    )

    # JSONB y no JSON: se guarda parseado, entra más chico y es consultable con
    # los operadores de Postgres sin castear en cada query.
    messages: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
