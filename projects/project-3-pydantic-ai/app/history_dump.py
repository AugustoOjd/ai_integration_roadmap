"""Mira qué quedó guardado, crudo.

    uv run python -m app.history_dump conv_xxx
    uv run python -m app.history_dump conv_xxx --raw

Sin --raw muestra un resumen por mensaje: qué tipo es y qué partes tiene.
Con --raw, el JSON entero tal como está en la columna JSONB.
"""

import argparse
import asyncio
import json

from app.core.db import SessionFactory, engine
from app.core.models import Conversation


async def main() -> None:
    parser = argparse.ArgumentParser(description="Inspecciona un historial guardado.")
    parser.add_argument("conversation")
    parser.add_argument("--raw", action="store_true", help="El JSON completo.")
    args = parser.parse_args()

    async with SessionFactory() as session:
        conv = await session.get(Conversation, args.conversation)

    if conv is None:
        raise SystemExit(f"No existe la conversación {args.conversation}.")

    if args.raw:
        print(json.dumps(conv.messages, indent=2, ensure_ascii=False))
    else:
        print(f"{len(conv.messages)} mensajes · cliente {conv.customer_id}\n")
        for i, msg in enumerate(conv.messages):
            # `kind` distingue request de response; `part_kind` distingue qué
            # hay adentro. Los dos los puso el framework, no nosotros.
            partes = [p.get("part_kind", "?") for p in msg.get("parts", [])]
            print(f"  {i:>2}  {msg.get('kind', '?'):<9} {', '.join(partes)}")

        tamano = len(json.dumps(conv.messages))
        print(f"\n{tamano} bytes de JSON")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
