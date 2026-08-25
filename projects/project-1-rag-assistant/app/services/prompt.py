"""Ensamblado del prompt en cuatro bloques.

    [system]     fijo, siempre del servidor, siempre primero
    [historial]  ultimos turnos, ya recortados por el schema
    [contexto]   chunks recuperados ESTE turno
    [pregunta]   el turno actual

El contexto va pegado a la pregunta actual, no como mensaje aparte: asi no se
acumula turno tras turno. Con TOP_K=5 son ~2.000 tokens por turno; arrastrarlos
llenaria la ventana en pocos mensajes y diluiria la atencion del modelo sobre
los chunks que si importan ahora.
"""

from app.services.search import SearchHit

# En ingles, no por preferencia: el modelo tiende a responder en el idioma del
# system prompt, y eso pesa mas que una instruccion dentro de el. Escribirlo en
# espanol hacia que preguntas en ingles se respondieran en espanol.
#
# Sin mencion al dominio: sirve igual para un reglamento que para una novela.
SYSTEM_PROMPT = """You answer questions about a set of documents.

Rules:
- Answer ONLY from the CONTEXT. Never use your own knowledge.
- If the context does not contain the answer, say so plainly. Do not invent.
- Cite each claim with its number: [1], [2].
- Always reply in the SAME LANGUAGE as the question, not this prompt's language.
- Answer directly. Do not preface with "According to the context"."""


def format_context(hits: list[SearchHit]) -> str:
    """Los chunks numerados, para que el modelo pueda citarlos como [1], [2]."""
    bloques = []
    for numero, hit in enumerate(hits, start=1):
        origen = hit.source
        if hit.page is not None:
            origen += f", pagina {hit.page}"
        bloques.append(f"[{numero}] {origen}\n{hit.text}")
    return "\n\n".join(bloques)


def build_messages(
    question: str,
    hits: list[SearchHit],
    history: list[dict],
) -> list[dict]:
    """Los cuatro bloques, en orden."""
    return [
        # El system siempre lo pone el servidor y va primero.
        {"role": "system", "content": SYSTEM_PROMPT},
        *history,
        {
            "role": "user",
            "content": f"CONTEXTO:\n{format_context(hits)}\n\nPREGUNTA: {question}",
        },
    ]
