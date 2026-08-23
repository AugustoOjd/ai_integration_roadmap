import logging
import re
from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.config import settings

logger = logging.getLogger(__name__)

# Colapsa espacios, tabs y saltos repetidos. pypdf produce mucho de esto por el
# layout en columnas, y desperdiciaría el presupuesto de cada chunk.
_ESPACIOS = re.compile(r"\s+")


class ExtractionError(Exception):
    """No se pudo sacar texto del archivo. La ruta lo traduce a un 4xx."""


def extract_document_text(contenido: bytes, filename: str) -> str:
    """Texto plano de un .pdf o un .txt."""
    nombre = filename.lower()

    if nombre.endswith(".txt"):
        # errors="replace" en vez de fallar: un byte suelto mal codificado no
        # debería tirar la subida entera.
        texto = contenido.decode("utf-8", errors="replace")
    elif nombre.endswith(".pdf"):
        texto = _pdf_to_text(contenido)
    else:
        raise ExtractionError(f"Formato no soportado: {filename}. Solo .pdf y .txt")

    texto = _ESPACIOS.sub(" ", texto).strip()

    if not texto:
        # Caso típico: PDF escaneado, que son imágenes sin capa de texto.
        # pypdf devuelve cadenas vacías sin dar error.
        raise ExtractionError(
            f"No se extrajo texto de {filename}. "
            "Si es un PDF escaneado, necesita OCR (fuera del alcance de este mini)."
        )
    return texto


def _pdf_to_text(contenido: bytes) -> str:
    """Concatena el texto de todas las páginas.

    BytesIO envuelve los bytes como archivo: pypdf necesita algo con .read() y
    .seek(), y así evitamos escribir a disco.
    """
    try:
        reader = PdfReader(BytesIO(contenido))
    except PdfReadError as exc:
        raise ExtractionError(f"PDF ilegible o corrupto: {exc}") from exc

    # extract_text() devuelve None en páginas sin capa de texto: el `or ""` evita
    # un TypeError al unir.
    paginas = [pagina.extract_text() or "" for pagina in reader.pages]
    logger.info("PDF de %d páginas", len(paginas))
    return "\n".join(paginas)


def chunk_text(
    texto: str,
    chunk_size: int | None = None,
    overlap: int | None = None,
) -> list[str]:
    """Parte el texto en ventanas solapadas.

    El solape existe porque el corte es por posición, no por significado: una
    idea partida al final de un chunk reaparece completa al inicio del siguiente.
    """
    chunk_size = chunk_size or settings.CHUNK_SIZE
    overlap = overlap or settings.CHUNK_OVERLAP

    # Con overlap >= chunk_size el avance sería 0 o negativo: bucle infinito.
    if overlap >= chunk_size:
        raise ValueError(f"overlap ({overlap}) debe ser menor que chunk_size ({chunk_size})")

    total = len(texto)
    # Margen para retroceder al espacio anterior sin encoger demasiado el chunk.
    margen = chunk_size // 10

    chunks: list[str] = []
    inicio_chunk = 0

    while inicio_chunk < total:
        fin_chunk = min(inicio_chunk + chunk_size, total)

        # Salvo en el último chunk, retrocede hasta el espacio más cercano para
        # no cortar una palabra por la mitad.
        if fin_chunk < total:
            corte = texto.rfind(" ", fin_chunk - margen, fin_chunk)
            if corte != -1:
                fin_chunk = corte

        chunk = texto[inicio_chunk:fin_chunk].strip()
        if chunk:
            chunks.append(chunk)

        # Después del append, para no perder el último chunk. Sin este break
        # inicio_chunk se estancaría antes del final y el bucle no terminaría.
        if fin_chunk >= total:
            break

        # No avanza hasta fin_chunk, sino `overlap` antes: eso es el solape.
        inicio_chunk = fin_chunk - overlap

    return chunks
