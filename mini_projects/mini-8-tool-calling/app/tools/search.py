"""La tool `search`.

Es un stub sobre un corpus local, y está bien que lo sea: lo que esta fase
enseña de `search` no es cómo hablar con un buscador, sino cómo se comporta una
tool que toca el mundo exterior. Esas reglas no cambian según el proveedor.

    1. TODO lo que devuelve una tool entra al contexto y lo pagás en tokens, en
       CADA vuelta del loop que venga después. Una tool charlatana es cara de
       una forma que no se nota hasta la factura.
    2. Una tool que llama a la red necesita timeout SIEMPRE. Sin él, un
       servicio colgado cuelga tu request, que cuelga un worker de uvicorn.
    3. El tamaño de la respuesta se acota antes de devolverla, no después.

Para convertirla en una búsqueda real hay que cambiar una sola línea —el
`_CORPUS` por un `httpx.get(..., timeout=...)`— y dejar el resto igual. Los
recortes de abajo son exactamente los que necesitarías.
"""

from typing import Annotated

from pydantic import Field

from app.tools.registry import registry

# Cuántos resultados devolver como máximo. Un buscador te da diez o cien; el
# modelo casi nunca necesita más de tres, y cada uno que agregues lo vas a
# pagar en todas las llamadas siguientes del loop.
MAX_RESULTS = 3

# Cuántos caracteres por snippet. Es el techo que impide que una página larga
# se te meta entera en el contexto.
MAX_SNIPPET_CHARS = 300

# El "índice". En la versión real esto es la respuesta del buscador.
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

    El índice es acotado y cubre pocos temas: si no hay resultados, decilo en
    vez de responder de memoria.
    """
    # Esa última frase del docstring es una instrucción de comportamiento, no
    # una descripción. Sin ella, el patrón habitual ante una búsqueda vacía es
    # que el modelo conteste igual desde su entrenamiento, sin aclarar que no
    # encontró nada — que es justo el problema que la tool venía a resolver.
    terms = query.lower().split()

    results = []
    for topic, text in _CORPUS.items():
        # Coincidencia si cualquier término aparece en el tema o en el texto.
        if not any(term in topic or term in text.lower() for term in terms):
            continue

        results.append(
            {
                "title": topic,
                # El recorte se hace ACÁ, no en quien consuma esto. Si dejás
                # pasar el texto completo confiando en que alguien lo corte más
                # adelante, en algún momento alguien no lo corta.
                "snippet": _truncate(text, MAX_SNIPPET_CHARS),
            }
        )

        # Corte temprano: ni siquiera formateamos lo que no vamos a devolver.
        if len(results) == MAX_RESULTS:
            break

    return results


def _truncate(text: str, limit: int) -> str:
    """Recorta y marca el recorte.

    El '…' importa: le dice al modelo que el texto sigue. Sin la marca, un
    fragmento cortado al medio parece un texto completo que termina raro, y el
    modelo puede sacar conclusiones de una frase mutilada.
    """
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
