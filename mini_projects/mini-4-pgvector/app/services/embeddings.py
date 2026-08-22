import asyncio
import logging

import numpy as np
from sentence_transformers import SentenceTransformer
from transformers.utils import logging as hf_logging

from app.config import NORMALIZE_EMBEDDINGS, settings

logger = logging.getLogger(__name__)

# La barra "Loading weights" es tqdm a stderr, no logging: no la apaga el
# setLevel de main.py.
hf_logging.disable_progress_bar()


class EmbeddingService:
    """Un modelo cargado y las operaciones que lo necesitan.

    Portado de mini-3, pero con un solo modelo: la columna es vector(384) fija,
    así que un modelo de otro tamaño no podría escribir en la tabla.
    """

    def __init__(self, model_name: str):
        self.model_name = model_name
        # Carga perezosa: construir el servicio es instantáneo.
        self._model: SentenceTransformer | None = None

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def load(self) -> SentenceTransformer:
        """Carga el modelo en memoria. Idempotente."""
        if self._model is None:
            logger.info("Cargando %r (la primera vez lo descarga)...", self.model_name)
            self._model = SentenceTransformer(self.model_name)
            logger.info(
                "Cargado %r — %s dimensiones",
                self.model_name,
                self._model.get_embedding_dimension(),
            )
        return self._model

    @property
    def dimension(self) -> int:
        """Tamaño de salida, preguntado al modelo para que no pueda desviarse."""
        dimension = self.load().get_embedding_dimension()
        if dimension is None:
            raise RuntimeError(f"El modelo {self.model_name!r} no tiene dimensión fija")
        return dimension

    def _encode_sync(self, text: str) -> np.ndarray:
        """Corre el modelo. Bloqueante y CPU-bound — llégale por embed().

        convert_to_numpy=True ya es el default, pero pasarlo explícito es lo que
        elige la sobrecarga tipada `-> np.ndarray` en vez de la que da un Tensor.
        """
        return self.load().encode(
            text,
            convert_to_numpy=True,
            normalize_embeddings=NORMALIZE_EMBEDDINGS,
        )

    def _encode_many_sync(self, texts: list[str]) -> np.ndarray:
        """Igual que _encode_sync pero por lotes.

        batch_size agrupa los textos en una sola multiplicación de matrices:
        embeber 10.000 de uno en uno tarda un orden de magnitud más.
        """
        return self.load().encode(
            texts,
            batch_size=64,
            convert_to_numpy=True,
            normalize_embeddings=NORMALIZE_EMBEDDINGS,
            show_progress_bar=False,
        )

    async def embed(self, text: str) -> list[float]:
        """Texto a vector sin bloquear el event loop.

        Son ~10-20ms de multiplicación de matrices, no espera de red: llamado
        directo frenaría todos los demás requests. to_thread basta porque
        PyTorch suelta el GIL durante el cálculo.
        """
        vector = await asyncio.to_thread(self._encode_sync, text)
        return vector.tolist()  # numpy array -> lista, para pgvector y Pydantic

    async def embed_many(self, texts: list[str]) -> list[list[float]]:
        """Versión por lotes de embed(). La usa el seed."""
        vectors = await asyncio.to_thread(self._encode_many_sync, texts)
        return vectors.tolist()


# Instancia única compartida. Declarada aquí, pero el modelo no se carga hasta
# que el lifespan de main.py lo pide.
embedding_service = EmbeddingService(settings.MODEL_NAME)
