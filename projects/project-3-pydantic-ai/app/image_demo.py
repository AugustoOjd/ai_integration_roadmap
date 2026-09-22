"""Una capability que el modelo decide usar por su cuenta.

    uv run python -m app.image_demo

Necesita OPENAI_API_KEY: Anthropic no genera imágenes, así que Haiku delega en
un modelo de imagen vía `fallback_image_model`. El agente no sabe nada de eso.

Es el ejemplo más claro de qué es una *capability*: no es una tool que
registraste ni un toolset que compusiste, es una funcionalidad que el framework
resuelve nativa-o-por-fallback según el provider que tengas puesto.
"""

import asyncio
from pathlib import Path

from pydantic_ai import Agent, BinaryImage
from pydantic_ai.capabilities import ImageGeneration

from app.core.config import settings

SALIDA = Path("out")


async def main() -> None:
    if settings.OPENAI_API_KEY is None:
        raise SystemExit(
            "Falta OPENAI_API_KEY. Anthropic no genera imágenes; esta fase "
            "necesita un segundo provider."
        )

    # Agente propio y mínimo: el de triage tiene output_type y no viene al caso.
    ilustrador = Agent(
        settings.AGENT_MODEL,
        capabilities=[
            ImageGeneration(
                # Haiku no tiene tool nativa de imágenes: cae al modelo de abajo.
                native=False,
                fallback_image_model="openai:gpt-image-1",
                output_format="png",
            )
        ],
        instructions="Ilustrás conceptos con imágenes simples y planas.",
    )

    result = await ilustrador.run(
        "Dibujá un paquete de envío con una etiqueta de 'devolución'."
    )

    SALIDA.mkdir(exist_ok=True)
    # Las imágenes vuelven como partes del mensaje, no como el output.
    for msg in result.all_messages():
        for part in msg.parts:
            contenido = getattr(part, "content", None)
            if isinstance(contenido, BinaryImage):
                destino = SALIDA / f"{contenido._identifier}.png"
                destino.write_bytes(contenido.data)
                print(f"  {destino}  ({len(contenido.data)} bytes, {contenido.media_type})")

    print(f"\n{result.usage.requests} requests")


if __name__ == "__main__":
    asyncio.run(main())
