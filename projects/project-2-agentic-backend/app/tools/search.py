"""La tool `search`.

Un stub sobre un corpus local. Lo que enseña no es cómo hablar con un buscador
sino cómo se comporta una tool que toca el mundo exterior, y esas reglas no
cambian según el proveedor:

    1. Todo lo que devuelve entra al contexto y se paga en tokens, en cada vuelta
       del loop que venga después.
    2. Una tool que llama a la red necesita timeout siempre.
    3. El tamaño de la respuesta se acota antes de devolverla, no después.

Para convertirla en una búsqueda real se cambia el `_CORPUS` por un
`httpx.get(..., timeout=...)` y el resto queda igual.
"""

from typing import Annotated

from pydantic import Field

from app.tools.registry import registry

# Un buscador devuelve diez o cien resultados; el modelo casi nunca necesita más
# de tres, y cada uno se paga en todas las llamadas siguientes del loop.
MAX_RESULTS = 3

# El techo que impide que una página larga se meta entera en el contexto.
MAX_SNIPPET_CHARS = 300

# El "índice". En la versión real, la respuesta del buscador.
_CORPUS: dict[str, str] = {
    "python": (
        "Python es un lenguaje de programación interpretado, de tipado dinámico "
        "y multiparadigma, creado por Guido van Rossum y publicado en 1991."
    ),
    "fastapi": (
        "FastAPI es un framework web de Python para construir APIs, basado en "
        "type hints estándar. Usa Starlette para el manejo HTTP y Pydantic para "
        "la validación de datos."
    ),
    "celery": (
        "Celery es una cola de tareas distribuida para Python, usada para "
        "ejecutar trabajo en background fuera del ciclo request/response."
    ),
    "tool calling": (
        "Tool calling es el mecanismo por el cual un modelo de lenguaje pide la "
        "ejecución de una función externa. El modelo no ejecuta nada: devuelve "
        "una intención estructurada y el sistema que lo hospeda decide si la "
        "ejecuta y le devuelve el resultado."
    ),
}


@registry.tool
def search(
    query: Annotated[
        str,
        Field(description="Los términos a buscar. Ejemplo: 'fastapi validación'."),
    ],
) -> list[dict[str, str]]:
    """Busca información sobre un tema y devuelve fragmentos relevantes.

    Usala cuando la pregunta sea sobre hechos concretos que podrías no saber o
    que podrían haber cambiado. Devuelve una lista de resultados con título y
    fragmento; si no encuentra nada, devuelve una lista vacía.

    El índice es acotado y cubre pocos temas: si no hay resultados, decilo en vez
    de responder de memoria.
    """
    # Esa última frase es una instrucción de comportamiento, no una descripción.
    # Sin ella, ante una búsqueda vacía el modelo contesta igual desde su
    # entrenamiento sin aclarar que no encontró nada — el problema que la tool
    # venía a resolver.
    terms = query.lower().split()

    results = []
    for topic, text in _CORPUS.items():
        if not any(term in topic or term in text.lower() for term in terms):
            continue

        results.append(
            {
                "title": topic,
                # El recorte se hace acá y no en quien consuma esto: si dejás
                # pasar el texto completo confiando en que alguien lo corte más
                # adelante, en algún momento alguien no lo corta.
                "snippet": _truncate(text, MAX_SNIPPET_CHARS),
            }
        )

        if len(results) == MAX_RESULTS:
            break

    return results


def _truncate(text: str, limit: int) -> str:
    """Recorta y marca el recorte.

    El '…' le dice al modelo que el texto sigue. Sin la marca, un fragmento
    cortado al medio parece un texto completo y el modelo saca conclusiones de
    una frase mutilada.
    """
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
