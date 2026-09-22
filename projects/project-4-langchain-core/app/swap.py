"""El swap test: cuánto cuesta cambiar de modelo de embeddings.

    uv run python -m app.swap                                  # el de la config
    uv run python -m app.swap --model voyageai:voyage-3.5
    uv run python -m app.swap --model voyageai:voyage-3.5-lite --dim 256

Indexa el corpus con el modelo pedido en su propia colección, mide cuánto tarda,
y evalúa el retrieval contra el set de preguntas.

**Mide el retrieval, no la respuesta.** Lo único que cambia entre corridas es el
espacio vectorial; el modelo de chat es el mismo. Meter al LLM en la medición
agregaría ruido y costo sin decir nada sobre lo que cambió.

La métrica es hit rate: de las preguntas con fuente conocida, en cuántas el
top-k trajo al menos un chunk del documento correcto.
"""

import argparse
import asyncio
import json
import time

from langchain_core.embeddings import Embeddings

from app.core.config import settings
from app.core.store import embeddings, nombre_coleccion, store
from app.ingest import cargar, partir


async def con_reintentos(hacer, intentos: int = 4, espera: float = 25.0):
    """Reintenta ante rate limit.

    El free tier de Voyage son 3 requests por minuto, contando la ingesta y las
    consultas juntas. Sin esto el script falla al segundo paso.

    Va acá y no en la integración a propósito: `VoyageAIEmbeddings` no reintenta
    solo. El backoff ante rate limits sigue siendo tuyo.
    """
    for intento in range(intentos):
        try:
            return await hacer()
        except Exception as e:
            if "RateLimit" not in type(e).__name__ or intento == intentos - 1:
                raise
            print(f"  rate limit, esperando {espera:.0f}s…")
            await asyncio.sleep(espera)


async def embeber_consultas(emb: Embeddings, textos: list[str]) -> list[list[float]]:
    """Embebe todas las consultas de una.

    La interfaz `Embeddings` tiene `embed_documents` (lote) y `embed_query`
    (una sola). **No tiene un equivalente en lote para consultas.** Con un
    límite de 3 requests por minuto, esa asimetría convierte 17 preguntas en
    6 minutos de espera.

    Voyage sí soporta el lote; el método está abajo de la interfaz, sin
    exponerse. Por eso el getattr: si no está, se cae al bucle lento.
    """
    en_lote = getattr(emb, "_aembed_regular", None)
    if en_lote is not None:
        return await en_lote(textos, "query")
    return [await emb.aembed_query(t) for t in textos]


async def main() -> None:
    parser = argparse.ArgumentParser(description="Swap test de embeddings.")
    parser.add_argument("--model", default=settings.EMBEDDING_MODEL)
    parser.add_argument("--dim", type=int, help="Dimensiones de salida.")
    parser.add_argument("--k", type=int, default=settings.RETRIEVER_K)
    args = parser.parse_args()

    coleccion = nombre_coleccion(args.model, args.dim)
    print(f"modelo      {args.model}")
    print(f"colección   {coleccion}")

    chunks = partir(cargar())

    # ── Costo de indexar ────────────────────────────────────────────────
    vs = store(pre_delete=True, modelo=args.model, dim=args.dim)
    t0 = time.perf_counter()
    await con_reintentos(lambda: vs.aadd_documents(chunks))
    t_indexado = time.perf_counter() - t0

    print(f"\nindexado    {len(chunks)} chunks en {t_indexado:.2f}s")

    # ── Calidad del retrieval ───────────────────────────────────────────
    preguntas = json.loads(settings.PREGUNTAS.read_text(encoding="utf-8"))
    # Las que no tienen fuente (la de teletrabajo) no se pueden puntuar acá:
    # su respuesta correcta es una negativa, que depende del prompt.
    medibles = [p for p in preguntas if p["fuente"]]

    emb = embeddings(args.model, args.dim)
    vectores = await con_reintentos(
        lambda: embeber_consultas(emb, [p["question"] for p in medibles])
    )

    aciertos = 0
    fallos = []
    t0 = time.perf_counter()

    for p, vector in zip(medibles, vectores):
        # by_vector y no asimilarity_search: el embedding ya está hecho, así
        # el tiempo medido es sólo el de Postgres.
        docs = await vs.asimilarity_search_by_vector(vector, k=args.k)
        recuperadas = {d.metadata["source"] for d in docs}
        # Basta con UNA de las fuentes esperadas: para las de cruce de
        # documentos, exigir las dos mediría otra cosa.
        if recuperadas & set(p["fuente"]):
            aciertos += 1
        else:
            fallos.append((p["question"], p["fuente"], sorted(recuperadas)))

    t_busqueda = time.perf_counter() - t0

    print(f"búsqueda    {len(medibles)} consultas en {t_busqueda:.3f}s "
          f"({t_busqueda / len(medibles) * 1000:.0f} ms c/u)")
    print(f"hit rate    {aciertos}/{len(medibles)} "
          f"({aciertos / len(medibles) * 100:.0f}%) con k={args.k}")

    if fallos:
        print("\nfallos:")
        for pregunta, esperada, recuperada in fallos:
            print(f"  {pregunta}")
            print(f"    esperaba   {esperada}")
            print(f"    recuperó   {recuperada}")


if __name__ == "__main__":
    asyncio.run(main())
