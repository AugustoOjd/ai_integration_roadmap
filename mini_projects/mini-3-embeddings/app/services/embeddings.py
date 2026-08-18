import asyncio
import logging

import numpy as np
from sentence_transformers import SentenceTransformer

from app.config import NORMALIZE_EMBEDDINGS, settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    """One loaded embedding model, and the operations that need it.

    This is a class rather than a module because we want MORE THAN ONE: a Python
    module is already a singleton (imported once, cached in sys.modules), so it
    covers the "exactly one shared model" case perfectly well. The moment you want
    two models side by side, the module runs out of room and instances earn their
    place.
    """

    def __init__(self, model_name: str):
        self.model_name = model_name
        # Loaded lazily: constructing the service is instant, so we can declare
        # several of them without paying ~900MB of RAM for models nobody uses yet.
        self._model: SentenceTransformer | None = None

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def load(self) -> SentenceTransformer:
        """Load this model into memory. Idempotent — safe to call repeatedly.

        Note there is no `global` here: `self._model = ...` assigns an ATTRIBUTE
        of an object, and Python's local-scope rule only applies to bare names.
        """
        if self._model is None:
            logger.info("Loading %r (first run downloads it)...", self.model_name)
            self._model = SentenceTransformer(self.model_name)
            logger.info(
                "Loaded %r — %s dimensions",
                self.model_name,
                self._model.get_embedding_dimension(),
            )
        return self._model

    @property
    def dimension(self) -> int:
        """Output size, asked of the model itself so it can never drift from
        whatever is actually loaded."""
        dimension = self.load().get_embedding_dimension()
        if dimension is None:
            raise RuntimeError(f"Model {self.model_name!r} has no fixed output dimension")
        return dimension

    def _encode_sync(self, text: str) -> np.ndarray:
        """Run the model. Blocking and CPU-bound — reach it through embed().

        convert_to_numpy=True is already the runtime default, but passing it
        explicitly is what selects the `-> np.ndarray` overload: encode() declares
        eight typed overloads, and the one matching when the argument is omitted
        is typed as returning a torch Tensor instead.
        """
        return self.load().encode(
            text,
            convert_to_numpy=True,
            normalize_embeddings=NORMALIZE_EMBEDDINGS,
        )

    async def embed(self, text: str) -> list[float]:
        """Turn text into a vector, without blocking the event loop.

        This is CPU-bound work — real matrix multiplication busy for ~10-20ms —
        not the network waiting that `await` usually represents. Called directly
        from an async route it would stall every other request for that whole
        time. asyncio.to_thread moves it to a worker thread; threads suffice
        (rather than processes) because PyTorch releases the GIL during the math.
        """
        vector = await asyncio.to_thread(self._encode_sync, text)
        return vector.tolist()  # numpy array -> plain list, for Pydantic/JSON


# The models this app can use, by short alias. Both are declared up front but
# neither is loaded until something asks for it — see EmbeddingService.__init__.
SERVICES: dict[str, EmbeddingService] = {
    "default": EmbeddingService(settings.MODEL_NAME),
    "alt": EmbeddingService(settings.ALT_MODEL_NAME),
}


def get_service(alias: str) -> EmbeddingService:
    """Look up a service by alias, failing loudly on an unknown one."""
    try:
        return SERVICES[alias]
    except KeyError:
        raise KeyError(f"Unknown model alias {alias!r}. Available: {sorted(SERVICES)}") from None


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """How alike two vectors are, from -1 (opposite) to 1 (identical direction).

        similarity = (A · B) / (‖A‖ × ‖B‖)

    Deliberately NOT a method: it doesn't touch a model or any instance state, it
    just does math on two lists. Attaching it to EmbeddingService would imply a
    dependency that isn't there — and would make comparing vectors awkward, since
    you'd have to pick an arbitrary instance to call it on.

    It measures the ANGLE between the vectors, ignoring their length: magnitude
    tracks things like text length rather than meaning, so a long and a short text
    on the same topic should still score as similar.

    Written out in full so it works on any vectors. When both are normalized (our
    default), ‖A‖ × ‖B‖ = 1 and this reduces to just the dot product — which is why
    providers ship normalized vectors: it's a free speedup.
    """
    vec_a, vec_b = np.array(a), np.array(b)

    norms = np.linalg.norm(vec_a) * np.linalg.norm(vec_b)
    if norms == 0:  # a zero vector has no direction, so "angle" is undefined
        return 0.0

    similarity = float(np.dot(vec_a, vec_b) / norms)

    # Floating-point rounding can push an identical pair to 1.0000000000000002,
    # which would be an invalid cosine. Clamp back into the mathematical range.
    return max(-1.0, min(1.0, similarity))
