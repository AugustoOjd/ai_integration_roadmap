"""Guardar y recuperar el historial de un hilo.

El formato no lo elegimos nosotros: `ModelMessagesTypeAdapter` es el TypeAdapter
de Pydantic que serializa y valida la representación interna del framework.
Escribir un esquema propio sería inventar un segundo formato que hay que
mantener sincronizado con el de ellos.
"""

import json

from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import Conversation


async def cargar(session: AsyncSession, conv_id: str) -> list[ModelMessage]:
    """El historial de un hilo, listo para pasar a `message_history=`.

    validate_python reconstruye los objetos: lo que sale no son dicts, son
    ModelRequest/ModelResponse con sus partes tipadas.
    """
    conv = await session.get(Conversation, conv_id)
    if conv is None:
        raise ValueError(f"No existe la conversación {conv_id}.")
    return ModelMessagesTypeAdapter.validate_python(conv.messages)


async def guardar(
    session: AsyncSession,
    conv_id: str | None,
    customer_id: str,
    mensajes_json: bytes,
) -> str:
    """Pisa el historial del hilo con el acumulado del run. Devuelve el id.

    Se guarda todo y no sólo lo nuevo: el framework ya entrega el acumulado, y
    un append parcial obligaría a razonar sobre qué mensajes se solapan entre
    runs.
    """
    # Los bytes de all_messages_json() son JSON; JSONB los quiere parseados.
    mensajes = json.loads(mensajes_json)

    conv = await session.get(Conversation, conv_id) if conv_id else None
    if conv is None:
        conv = Conversation(customer_id=customer_id)
        if conv_id:
            conv.id = conv_id
        session.add(conv)

    conv.messages = mensajes
    await session.commit()
    return conv.id


async def listar(session: AsyncSession, customer_id: str) -> list[Conversation]:
    stmt = (
        select(Conversation)
        .where(Conversation.customer_id == customer_id)
        .order_by(Conversation.updated_at.desc())
    )
    return list(await session.scalars(stmt))
