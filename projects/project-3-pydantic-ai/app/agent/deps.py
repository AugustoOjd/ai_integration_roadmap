"""Lo que las tools necesitan y el modelo nunca ve."""

from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

Role = Literal["customer", "agent"]


@dataclass
class Deps:
    """Se construye por run y se pasa a `agent.run(deps=...)`.

    `customer_id` sale de tu auth, no del modelo. Que esté acá y no como
    parámetro de una tool es la diferencia entre "el modelo pide sus órdenes" y
    "el modelo pide las órdenes de quien quiera".
    """

    # La FÁBRICA, no una sesión: Pydantic AI corre las tool calls de un mismo
    # turno en paralelo, y una AsyncSession compartida entre dos corutinas tira
    # InvalidRequestError. Cada tool abre la suya.
    session_factory: async_sessionmaker[AsyncSession]

    customer_id: str

    # Quién está del otro lado: el cliente mismo o alguien de soporte. Decide
    # qué tools existen en este run, no qué hace cada tool.
    role: Role = "customer"
