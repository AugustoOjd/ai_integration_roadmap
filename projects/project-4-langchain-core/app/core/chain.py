"""La cadena: retriever → prompt → modelo → parser, compuesta con `|`.

Es el mismo grafo que escribirías a mano. La diferencia es que acá se **declara**
y en P1 se **ejecutaba**: lo que vuelve de `armar()` es un valor, no un
resultado. De eso salen gratis `.invoke`, `.batch`, `.stream` y los `a*`.
"""

from langchain.chat_models import init_chat_model
from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable, RunnablePassthrough

from app.core.config import settings
from app.core.store import store

SISTEMA = """\
Sos el asistente de políticas internas de Nordix Comercio.

Respondé ÚNICAMENTE con lo que diga el contexto. Si el contexto no alcanza para
responder, decí exactamente: "No encuentro esa información en las políticas."
No completes con conocimiento general ni supongas.

Citá el documento del que sacaste cada dato, por su nombre de archivo.

Contexto:
{context}"""

prompt = ChatPromptTemplate.from_messages(
    [("system", SISTEMA), ("human", "{question}")]
)


def formatear(docs: list[Document]) -> str:
    """Los Document del retriever a un string para el prompt.

    Este paso es tuyo: el retriever devuelve objetos y el prompt espera texto.
    Qué metadata entra acá decide si el modelo puede citar o no.
    """
    return "\n\n".join(
        f"[{d.metadata['source']}]\n{d.page_content}" for d in docs
    )


def armar() -> Runnable:
    """La cadena completa, lista para invoke/batch/stream."""
    retriever = store().as_retriever(search_kwargs={"k": settings.RETRIEVER_K})
    modelo = init_chat_model(settings.CHAT_MODEL, temperature=0)

    # El dict es un RunnableParallel implícito: las dos ramas corren a la vez.
    # "context" pasa por el retriever y el formateador; "question" pasa intacta.
    # En P1 esto hubiera sido un asyncio.gather escrito a mano.
    return (
        {
            "context": retriever | formatear,
            "question": RunnablePassthrough(),
        }
        | prompt
        | modelo
        | StrOutputParser()
    )


def armar_con_fuentes() -> Runnable:
    """La misma cadena, pero devolviendo también los chunks que la alimentaron.

    `armar()` los pierde: el retriever produce Document, `formatear` los
    convierte a texto, y ahí desaparecen. La cadena escondió su paso intermedio.

    Recuperarlos obliga a cambiar la forma: en vez de encadenar, se va
    acumulando un dict con `assign`, que agrega claves sin descartar las
    anteriores. El resultado ya no es un string sino {docs, question, answer}.

    Ese cambio de forma ES el costo de componer en lugar de ejecutar.
    """
    retriever = store().as_retriever(search_kwargs={"k": settings.RETRIEVER_K})
    modelo = init_chat_model(settings.CHAT_MODEL, temperature=0)

    return (
        {"docs": retriever, "question": RunnablePassthrough()}
        | RunnablePassthrough.assign(context=lambda x: formatear(x["docs"]))
        | RunnablePassthrough.assign(
            answer=prompt | modelo | StrOutputParser()
        )
    )
