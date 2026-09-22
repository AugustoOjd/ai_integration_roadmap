"""Embeddings y vector store. Un solo lugar donde se nombra al provider."""

import re

from langchain.embeddings import init_embeddings
from langchain_core.embeddings import Embeddings
from langchain_postgres import PGVector
from langchain_voyageai import VoyageAIEmbeddings

from app.core.config import settings


def embeddings(modelo: str | None = None, dim: int | None = None) -> Embeddings:
    """El provider sale de un string; lo que vuelve cumple `Embeddings`.

    Nada aguas abajo —el store, el retriever, la cadena— sabe cuál es.

    `init_embeddings` resuelve el string contra un registro **cerrado**:
    voyageai no está, aunque `langchain-voyageai` implemente la interfaz igual
    que los demás. Por eso ese caso se construye a mano.

    La interfaz es abierta; la capa de strings es una lista enumerada.
    """
    modelo = modelo or settings.EMBEDDING_MODEL
    provider, _, nombre = modelo.partition(":")

    if provider == "voyageai":
        # output_dimension recorta el vector: menos storage y comparaciones más
        # rápidas, a cambio de recall. Es una decisión tuya, no del provider.
        return VoyageAIEmbeddings(model=nombre, output_dimension=dim or 1024)

    return init_embeddings(modelo)


def nombre_coleccion(modelo: str, dim: int | None = None) -> str:
    """Una colección por espacio vectorial.

    Vectores de modelos distintos no se comparan entre sí: es matemática, no
    LangChain. El store te deja mezclarlos igual y no avisa.
    """
    base = re.sub(r"[^a-z0-9]+", "_", modelo.lower()).strip("_")
    return f"nordix_{base}" + (f"_{dim}" if dim else "")


def store(
    pre_delete: bool = False,
    modelo: str | None = None,
    dim: int | None = None,
) -> PGVector:
    """El vector store, apuntando a la colección del modelo pedido.

    Args:
        pre_delete: borra la colección antes de escribir. Para re-indexar sin
            duplicar chunks, porque add_documents no deduplica.
        modelo: override del EMBEDDING_MODEL de la config, para el swap test.
        dim: override de las dimensiones.
    """
    modelo = modelo or settings.EMBEDDING_MODEL
    coleccion = (
        settings.COLLECTION if modelo == settings.EMBEDDING_MODEL and dim is None
        else nombre_coleccion(modelo, dim)
    )

    return PGVector(
        embeddings=embeddings(modelo, dim),
        connection=str(settings.DATABASE_URL),
        collection_name=coleccion,
        # JSONB para la metadata: consultable con los operadores de Postgres.
        use_jsonb=True,
        pre_delete_collection=pre_delete,
        # Sin esto sólo construye el engine sincrónico y los métodos a* fallan
        # con "AssertionError: _async_engine not found". A cambio, los métodos
        # sincrónicos dejan de estar disponibles: es uno u otro.
        async_mode=True,
    )
