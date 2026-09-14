"""Verificación de la Fase 0: crear el esquema, escribir y volver a leer.

    uv run python -m scripts.db_smoke

No llama al modelo. Lo único que prueba es que la cañería de datos funciona —
que es exactamente lo que tiene que estar firme antes de la Fase 1, donde el
historial empieza a depender de ella.

Escribe un `tool_use` y su `tool_result` a propósito, aunque la Fase 0 no los
necesite todavía: son el dato más frágil del mini y conviene ver desde ahora que
sobreviven la ida y vuelta a JSONB sin deformarse.
"""

import asyncio
import json

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db import SessionFactory, create_schema, engine
from app.models import ChatSession, ExecutionStep, Message


async def main() -> None:
    await create_schema()
    print("✓ esquema creado (o ya estaba)")

    # ---- Escribir ---------------------------------------------------------
    #
    # Una sesión de base por unidad de trabajo. Acá va todo junto en una
    # transacción, que es el patrón que la Fase 1 va a formalizar en
    # `save_turn`: un turno entero, o nada.
    async with SessionFactory() as db:
        chat = ChatSession(
            user_id="u_42",
            budget_tokens=settings.DEFAULT_BUDGET_TOKENS,
        )
        db.add(chat)

        # `flush` manda los INSERT a la base SIN cerrar la transacción. Hace
        # falta acá porque los mensajes necesitan el `id` de la sesión, y ese id
        # lo genera el default de Python al insertar. Es la diferencia clave con
        # `commit`: flush = "escribí, pero seguimos adentro de la transacción".
        await db.flush()

        # El historial de un turno de ejemplo, en el formato EXACTO en que viaja
        # a la Messages API: `content` es una lista de bloques, no un string.
        historia = [
            (
                "user",
                [{"type": "text", "text": "¿cuánto es 42 por 2?"}],
            ),
            (
                "assistant",
                [
                    {"type": "text", "text": "Voy a calcularlo."},
                    {
                        "type": "tool_use",
                        "id": "toolu_demo_1",
                        "name": "calculate",
                        "input": {"expression": "42 * 2"},
                    },
                ],
            ),
            (
                # Contraintuitivo y correcto: el `tool_result` que escribís VOS
                # va con rol "user". Desde la perspectiva del modelo, vos sos el
                # usuario.
                "user",
                [
                    {
                        "type": "tool_result",
                        # Este id es lo único que correlaciona el resultado con
                        # el pedido. La Fase 1 entera se trata de no romperlo.
                        "tool_use_id": "toolu_demo_1",
                        "content": "84",
                    }
                ],
            ),
            (
                "assistant",
                [{"type": "text", "text": "42 por 2 es 84."}],
            ),
        ]

        db.add_all(
            Message(
                session_id=chat.id,
                turn=1,
                # La posición es explícita y la asigna quien escribe, no la base.
                position=posicion,
                role=rol,
                content=bloques,
            )
            for posicion, (rol, bloques) in enumerate(historia)
        )

        db.add(
            ExecutionStep(
                session_id=chat.id,
                turn=1,
                iteration=1,
                tool_name="calculate",
                tool_input={"expression": "42 * 2"},
                tool_output="84",
                latency_ms=3,
                input_tokens=412,
                output_tokens=58,
            )
        )

        await db.commit()
        # Esto sólo se puede imprimir después del commit gracias a
        # `expire_on_commit=False`: con el default de SQLAlchemy, tocar
        # `chat.id` acá dispararía un SELECT implícito que en async explota.
        print(f"✓ sesión escrita: {chat.id}")

    # ---- Leer -------------------------------------------------------------
    #
    # Sesión de base NUEVA a propósito. Reusar la anterior probaría poco: los
    # objetos siguen en su mapa de identidad y podría devolverlos de memoria sin
    # tocar Postgres. Con una sesión limpia, lo que vuelve viene de la base.
    async with SessionFactory() as db:
        consulta = (
            select(ChatSession)
            .where(ChatSession.user_id == "u_42")
            # `selectinload` es obligatorio por el `lazy="raise"` de los
            # modelos: sin esto, tocar `recuperada.messages` levanta un error
            # explícito en vez de disparar una query implícita a tus espaldas.
            # Emite una segunda query con un `IN (...)`, en vez del JOIN de
            # `joinedload`, que es lo que conviene para colecciones grandes:
            # no multiplica las filas del padre.
            .options(selectinload(ChatSession.messages), selectinload(ChatSession.steps))
            .order_by(ChatSession.created_at.desc())
            .limit(1)
        )
        recuperada = (await db.execute(consulta)).scalar_one()

        print(f"✓ sesión leída:  {recuperada.id}")
        print(f"  dueño:         {recuperada.user_id}")
        print(f"  estado:        {recuperada.status}")
        print(f"  presupuesto:   {recuperada.budget_tokens} tokens")
        print(f"  mensajes:      {len(recuperada.messages)}")
        print(f"  pasos:         {len(recuperada.steps)}")

        print("\n  historial tal cual volvió de JSONB:")
        for mensaje in recuperada.messages:
            print(f"    [{mensaje.position}] {mensaje.role}: {json.dumps(mensaje.content)}")

        # La prueba que importa: los pares siguen correlacionados después del
        # viaje de ida y vuelta. Si esto falla, la Fase 1 no tiene dónde pararse.
        pedidos = {
            bloque["id"]
            for mensaje in recuperada.messages
            for bloque in mensaje.content
            if bloque["type"] == "tool_use"
        }
        resultados = {
            bloque["tool_use_id"]
            for mensaje in recuperada.messages
            for bloque in mensaje.content
            if bloque["type"] == "tool_result"
        }
        assert pedidos == resultados, f"pares rotos: {pedidos ^ resultados}"
        print(f"\n✓ pares tool_use/tool_result intactos: {sorted(pedidos)}")

    # Cerrar el pool antes de que termine el proceso. En un script suelto, sin
    # esto asyncio suele quejarse de conexiones que quedaron abiertas al salir.
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
