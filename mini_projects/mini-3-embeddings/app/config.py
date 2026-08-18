from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Deployment configuration — values that can legitimately differ between
    environments. Each field is filled from an env var of the same name."""

    # Which sentence-transformers model to load. In .env because swapping models
    # is exactly what you want to experiment with, without touching code.
    MODEL_NAME: str = "all-MiniLM-L6-v2"

    # A second model, to compare against the first. Only loaded if you actually
    # request it — declaring it here costs nothing.
    ALT_MODEL_NAME: str = "paraphrase-multilingual-MiniLM-L12-v2"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


# Instantiated once at import time; every module imports this same `settings` object
settings = Settings()


# Deliberately NOT a setting. Whether vectors are normalized is an application
# design decision, not something that should vary per environment: flipping it
# once embeddings are stored would leave normalized and unnormalized vectors
# mixed in the same dataset, and comparing them would return meaningless numbers.
NORMALIZE_EMBEDDINGS = True

# There is no EMBEDDING_DIMENSION here on purpose. The output size is a fact
# about the loaded model, not a choice — ask the model for it via
# services.embeddings.get_dimension(), which can never drift from reality.
