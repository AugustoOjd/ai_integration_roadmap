"""La API de embeddings del ecosistema.

    uv run python -m app.embeddings_demo            # con TestEmbeddingModel
    uv run python -m app.embeddings_demo --real     # necesita OPENAI_API_KEY

Anthropic no ofrece embeddings, así que esto siempre habla con otro provider.
Sin key corre igual contra el modelo de prueba: lo que se ve es la forma de la
API, no la calidad de los vectores.
"""

import argparse
import asyncio

from pydantic_ai import Embedder
from pydantic_ai.embeddings import TestEmbeddingModel

from app.core.config import settings

# Las descripciones del seed: lo que indexarías.
DOCUMENTOS = [
    "Auriculares BT",
    "Funda de silicona",
    'Monitor 27"',
    "Cable HDMI",
    "Teclado mecánico",
]

CONSULTA = "algo para escuchar música"


async def main() -> None:
    parser = argparse.ArgumentParser(description="Embeddings, de un vistazo.")
    parser.add_argument(
        "--real", action="store_true", help="Usa OpenAI en vez del modelo de prueba."
    )
    args = parser.parse_args()

    if args.real:
        if settings.OPENAI_API_KEY is None:
            raise SystemExit("Falta OPENAI_API_KEY en el .env.")
        embedder = Embedder("openai:text-embedding-3-small")
    else:
        # dimensions=8 para que los vectores entren en pantalla.
        embedder = Embedder(TestEmbeddingModel(dimensions=8))

    # Dos métodos y no uno: los modelos asimétricos codifican distinto una
    # pregunta que un documento. Usar el mismo para ambos degrada el retrieval
    # sin que ningún error te avise.
    consulta = await embedder.embed_query(CONSULTA)
    docs = await embedder.embed_documents(DOCUMENTOS)

    print(f"consulta   {CONSULTA!r}")
    print(f"           {len(consulta.embeddings[0])} dimensiones")
    print(f"           {consulta.embeddings[0][:6]}…\n")

    print(f"{len(docs.embeddings)} documentos embebidos")
    # EmbeddingResult se indexa por posición o por el texto de entrada.
    print(f"  por texto    {docs['Cable HDMI'][:4]}…")
    print(f"  por índice   {docs[3][:4]}…")

    # El uso viaja con el resultado, igual que en un run del agente.
    print(f"\ntokens     {docs.usage.input_tokens}")
    if args.real:
        print(f"costo      {docs.cost()}")


if __name__ == "__main__":
    asyncio.run(main())
