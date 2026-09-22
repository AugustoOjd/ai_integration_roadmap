"""Una pregunta contra el corpus.

    uv run python -m app.ask "¿cuántos días tengo para devolver electrónica?"
    uv run python -m app.ask --graph      # qué construyó el `|`
    uv run python -m app.ask --batch      # tres preguntas en paralelo
"""

import argparse
import asyncio

from app.core.chain import armar, armar_con_fuentes

BATCH = [
    "¿Cuántos días tengo para devolver un producto de electrónica?",
    "¿Quién autoriza un reembolso de 150.000 pesos?",
    "¿Cuál es la política de teletrabajo de Nordix?",
]


async def main() -> None:
    parser = argparse.ArgumentParser(description="Pregunta al corpus.")
    parser.add_argument("pregunta", nargs="?")
    parser.add_argument(
        "--graph", action="store_true", help="Imprime la estructura de la cadena."
    )
    parser.add_argument(
        "--batch", action="store_true", help="Tres preguntas en una sola llamada."
    )
    parser.add_argument(
        "--stream", action="store_true", help="Imprime la respuesta a medida que llega."
    )
    parser.add_argument(
        "--sources", action="store_true", help="Muestra qué chunks alimentaron la respuesta."
    )
    args = parser.parse_args()

    chain = armar()

    if args.graph:
        # El `|` no ejecutó nada: construyó un RunnableSequence. Esto lo muestra.
        grafo = chain.get_graph()
        for nodo in grafo.nodes.values():
            print(f"  {type(nodo.data).__name__:<28} {nodo.id[:8]}")
        print(f"\n{len(grafo.nodes)} nodos · {len(grafo.edges)} aristas")
        print(f"\ntipo de la cadena: {type(chain).__name__}")
        return

    if args.batch:
        # Una llamada, tres cadenas completas en paralelo — retrieval incluido.
        for pregunta, respuesta in zip(BATCH, await chain.abatch(BATCH)):
            print(f"\n❯ {pregunta}\n{respuesta}")
        return

    if not args.pregunta:
        parser.error("hace falta una pregunta, o --graph, o --batch")

    if args.sources:
        r = await armar_con_fuentes().ainvoke(args.pregunta)
        print(r["answer"])
        print(f"\n─── {len(r['docs'])} chunks recuperados")
        for d in r["docs"]:
            inicio = d.metadata["start_index"]
            # Primera línea no vacía del chunk: alcanza para reconocerlo.
            primera = next(l for l in d.page_content.splitlines() if l.strip())
            print(f"  {d.metadata['source']:<24} @{inicio:<5} {primera[:52]}")
        return

    if args.stream:
        # Funciona porque TODOS los eslabones saben streamear. En P1 el SSE se
        # cableó a mano, una vez, para un solo camino.
        async for token in chain.astream(args.pregunta):
            print(token, end="", flush=True)
        print()
        return

    print(await chain.ainvoke(args.pregunta))


if __name__ == "__main__":
    asyncio.run(main())
