"""Indexa el corpus: loader → splitter → embeddings → PGVector.

    uv run python -m app.ingest
    uv run python -m app.ingest --dry-run    # parte y muestra, sin embeber

Re-ejecutarlo borra la colección y la vuelve a escribir: `add_documents` no
deduplica, así que sin el borrado previo cada corrida duplicaría los chunks.
"""

import argparse
import asyncio

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import settings
from app.core.store import store


def cargar() -> list[Document]:
    """El loader. Para .txt no hace falta uno de LangChain: es leer archivos.

    Lo que sí importa es la metadata — es lo único que sobrevive al chunking y
    lo que después permite citar de qué documento salió una respuesta.
    """
    docs = []
    for archivo in sorted(settings.CORPUS_DIR.glob("*.txt")):
        texto = archivo.read_text(encoding="utf-8")
        # La primera línea de cada archivo es el título del documento.
        titulo = texto.splitlines()[0].strip()
        docs.append(
            Document(
                page_content=texto,
                metadata={"source": archivo.name, "titulo": titulo},
            )
        )
    return docs


def partir(docs: list[Document]) -> list[Document]:
    """Parte por párrafo → línea → palabra → carácter, en ese orden.

    Sólo baja al separador siguiente cuando el chunk todavía no entra. La
    metadata del documento se copia a cada chunk.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.CHUNK_SIZE,
        chunk_overlap=settings.CHUNK_OVERLAP,
        # add_start_index guarda en qué carácter del original empieza el chunk:
        # sirve para citar una posición, no sólo un archivo.
        add_start_index=True,
    )
    return splitter.split_documents(docs)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Indexa el corpus en PGVector.")
    parser.add_argument(
        "--dry-run", action="store_true", help="Parte y muestra, sin embeber."
    )
    args = parser.parse_args()

    docs = cargar()
    chunks = partir(docs)

    print(f"{len(docs)} documentos → {len(chunks)} chunks")
    for doc in docs:
        n = sum(1 for c in chunks if c.metadata["source"] == doc.metadata["source"])
        print(f"  {doc.metadata['source']:<24} {len(doc.page_content):>6} chars → {n} chunks")

    if args.dry_run:
        print(f"\n--- primer chunk ({len(chunks[0].page_content)} chars) ---")
        print(chunks[0].page_content)
        print(f"\nmetadata: {chunks[0].metadata}")
        return

    # Una sola llamada: el store embebe en lote y escribe. Los reintentos y el
    # batching contra la API del provider los maneja la integración.
    vs = store(pre_delete=True)
    await vs.aadd_documents(chunks)

    print(f"\nindexado en la colección {settings.COLLECTION!r}")


if __name__ == "__main__":
    asyncio.run(main())
