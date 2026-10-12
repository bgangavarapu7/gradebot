import os
from dataclasses import dataclass

# Local-development default; matches .env.example. Real deployments set DATABASE_URL.
DEFAULT_DATABASE_URL = "postgresql://gradebot:change-me-local-only@localhost:5432/gradebot"


@dataclass(frozen=True)
class Settings:
    database_url: str
    prompt_version: str
    llm_timeout_s: float
    backoff_base_s: float


def get_settings() -> Settings:
    return Settings(
        database_url=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
        prompt_version=os.environ.get("PROMPT_VERSION", "grade_v1"),
        llm_timeout_s=float(os.environ.get("LLM_TIMEOUT_S", "10")),
        backoff_base_s=float(os.environ.get("LLM_BACKOFF_BASE_S", "0.2")),
    )
