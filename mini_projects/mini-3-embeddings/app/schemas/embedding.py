from pydantic import BaseModel, Field

# Shared field definition so the three request schemas can't drift apart.
TextField = Field(min_length=1, max_length=10_000)

# Which entry of services.embeddings.SERVICES to use. A short alias rather than a
# raw model name, so callers can't make the server download arbitrary models.
ModelField = Field(default="default", description="Model alias: 'default' or 'alt'")


class EmbedRequest(BaseModel):
    """Request body for POST /embeddings/embed."""

    # min_length=1 rejects empty strings at the API boundary: embedding "" produces
    # a meaningless vector, so it's better to 422 than to return nonsense.
    text: str = TextField
    model: str = ModelField


class EmbedResponse(BaseModel):
    text: str
    model: str  # which model produced this — vectors from different models aren't comparable
    embedding: list[float]
    dimension: int


class SimilarityRequest(BaseModel):
    """Request body for POST /embeddings/similarity."""

    text1: str = TextField
    text2: str = TextField
    model: str = ModelField


class SimilarityResponse(BaseModel):
    text1: str
    text2: str
    model: str

    # Cosine similarity is mathematically bounded to [-1, 1]. In practice these
    # models rarely go below 0 for natural text, but the bounds reflect the math
    # rather than the empirical range.
    similarity: float = Field(ge=-1.0, le=1.0)


class CompareRequest(BaseModel):
    """Request body for POST /embeddings/compare-models."""

    text1: str = TextField
    text2: str = TextField


class ModelResult(BaseModel):
    """What one model scored for the pair."""

    model_name: str
    dimension: int
    similarity: float = Field(ge=-1.0, le=1.0)


class CompareResponse(BaseModel):
    text1: str
    text2: str
    results: dict[str, ModelResult]  # keyed by alias
