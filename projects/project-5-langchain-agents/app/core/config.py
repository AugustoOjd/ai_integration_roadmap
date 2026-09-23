"""What changes between environments, read from the environment and .env."""

import os
from pathlib import Path

from pydantic import PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Fields without a default are requirements: if missing, import fails."""

    ANTHROPIC_API_KEY: SecretStr

    # "<provider>:<model>". create_agent takes this string as-is.
    CHAT_MODEL: str = "anthropic:claude-haiku-4-5"

    # Tokens (input + output, summed over every model call) one run may spend.
    # Lower it from the shell to watch BudgetMiddleware cut a run short:
    #   RUN_TOKEN_BUDGET=1500 uv run python -m app.chat --trace "..."
    RUN_TOKEN_BUDGET: int = 20_000

    # Seconds a remote (MCP) tool call may take before we give up on it.
    # The adapter has no timeout of its own: without this, a frozen server
    # holds the run open indefinitely.
    REMOTE_TOOL_TIMEOUT_S: float = 5.0

    DATABASE_URL: PostgresDsn = "postgresql://nordix:nordix@localhost:5437/nordix"  # type: ignore[assignment]

    # Absolute path so `python -m app.x` works from any cwd.
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")


settings = Settings()  # type: ignore[call-arg]

# pydantic-settings loads .env into this object, not into os.environ. The
# LangChain clients read os.environ, so the key has to be exported.
# setdefault: a variable already set in the shell wins.
os.environ.setdefault("ANTHROPIC_API_KEY", settings.ANTHROPIC_API_KEY.get_secret_value())
