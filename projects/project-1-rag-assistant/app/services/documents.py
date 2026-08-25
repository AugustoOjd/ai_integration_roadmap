import logging
import re
from bisect import bisect_right
from dataclasses import dataclass
from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.config import settings

logger = logging.getLogger(__name__)

# Colapsa espacios, tabs y saltos repetidos. pypdf produce mucho de esto por el
# layout en columnas, y desperdiciaria el presupuesto de cada chunk.
_ESPACIOS = re.compile(r"\s+")


class ExtractionError(Exception):
    """No se pudo sacar texto del archivo. La ruta lo traduce a un 4xx."""


@dataclass(frozen=True)
class ExtractedDocument:
    """Texto completo mas el mapa de donde empieza cada pagina.

    Se guardan los offsets en vez de trocear pagina por pagina: asi el chunking
    es global y el solape cruza los saltos de pagina, que es donde mas se parten
    las frases.
    """

    text: str
    # (offset en text, numero de pagina). Vacio en formatos sin paginas.
    page_starts: list[tuple[int, int]]

    def page_at(self, offset: int) -> int | None:
        """Pagina a la que pertenece una posicion del texto."""
        if not self.page_starts:
            return None
        # bisect sobre los offsets: la ultima pagina que empieza antes o en offset.
        posiciones = [inicio for inicio, _ in self.page_starts]
        indice = bisect_right(posiciones, offset) - 1
        return self.page_starts[max(indice, 0)][1]


@dataclass(frozen=True)
class Chunk:
    """Un trozo y su posicion de inicio en el texto completo."""

    text: str
    start: int


def extract_document(contenido: bytes, filename: str) -> ExtractedDocument:
    """Texto plano de un .pdf o un .txt, con el mapa de paginas si lo hay."""
    nombre = filename.lower()

    if nombre.endswith(".txt"):
        # errors="replace" en vez de fallar: un byte suelto mal codificado no
        # deberia tirar la subida entera.
        texto = _ESPACIOS.sub(" ", contenido.decode("utf-8", errors="replace")).strip()
        documento = ExtractedDocument(text=texto, page_starts=[])
    elif nombre.endswith(".pdf"):
        documento = _pdf_to_document(contenido)
    else:
        raise ExtractionError(f"Formato no soportado: {filename}. Solo .pdf y .txt")

    if not documento.text:
        # Caso tipico: PDF escaneado, que son imagenes sin capa de texto.
        # pypdf devuelve cadenas vacias sin dar error.
        raise ExtractionError(
            f"No se extrajo texto de {filename}. "
            "Si es un PDF escaneado necesita OCR, fuera del alcance de este proyecto."
        )
    return documento


def _pdf_to_document(contenido: bytes) -> ExtractedDocument:
    """Une las paginas anotando donde empieza cada una.

    BytesIO envuelve los bytes como archivo: pypdf necesita algo con .read() y
    .seek(), y asi evitamos escribir a disco.
    """
    try:
        reader = PdfReader(BytesIO(contenido))
    except PdfReadError as exc:
        raise ExtractionError(f"PDF ilegible o corrupto: {exc}") from exc

    partes: list[str] = []
    page_starts: list[tuple[int, int]] = []
    cursor = 0

    # start=1 porque las paginas se citan como las ve el lector, no desde 0.
    for numero, pagina in enumerate(reader.pages, start=1):
        # extract_text() devuelve None en paginas sin capa de texto.
        limpia = _ESPACIOS.sub(" ", pagina.extract_text() or "").strip()
        if not limpia:
            continue

        page_starts.append((cursor, numero))
        partes.append(limpia)
        cursor += len(limpia) + 1  # +1 por el espacio que las une

    logger.info("PDF de %d paginas, %d con texto", len(reader.pages), len(partes))
    return ExtractedDocument(text=" ".join(partes), page_starts=page_starts)


def chunk_text(
    texto: str,
    chunk_size: int | None = None,
    overlap: int | None = None,
) -> list[Chunk]:
    """Parte el texto en ventanas solapadas.

    El solape existe porque el corte es por posicion, no por significado: una
    idea partida al final de un chunk reaparece completa al inicio del siguiente.
    """
    chunk_size = chunk_size or settings.CHUNK_SIZE
    overlap = overlap or settings.CHUNK_OVERLAP

    # Con overlap >= chunk_size el avance seria 0 o negativo: bucle infinito.
    if overlap >= chunk_size:
        raise ValueError(f"overlap ({overlap}) debe ser menor que chunk_size ({chunk_size})")

    total = len(texto)
    # Margen para retroceder al espacio anterior sin encoger demasiado el chunk.
    margen = chunk_size // 10

    chunks: list[Chunk] = []
    inicio_chunk = 0

    while inicio_chunk < total:
        fin_chunk = min(inicio_chunk + chunk_size, total)

        # Salvo en el ultimo chunk, retrocede hasta el espacio mas cercano para
        # no cortar una palabra por la mitad.
        if fin_chunk < total:
            corte = texto.rfind(" ", fin_chunk - margen, fin_chunk)
            if corte != -1:
                fin_chunk = corte

        recorte = texto[inicio_chunk:fin_chunk].strip()
        if recorte:
            chunks.append(Chunk(text=recorte, start=inicio_chunk))

        # Despues del append, para no perder el ultimo chunk.
        if fin_chunk >= total:
            break

        # No avanza hasta fin_chunk, sino `overlap` antes: eso es el solape.
        inicio_chunk = fin_chunk - overlap

        # El solape cae en una posicion arbitraria, asi que el chunk empezaria a
        # mitad de palabra ("rategy" en vez de "strategy"). Avanza al siguiente
        # espacio; si no hay ninguno en el margen, se queda donde estaba.
        siguiente = texto.find(" ", inicio_chunk, inicio_chunk + margen)
        if siguiente != -1:
            inicio_chunk = siguiente + 1

    return chunks
