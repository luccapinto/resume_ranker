import os
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central application settings, loaded from environment or `api/.env`."""

    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Storage ─────────────────────────────────────────────────────
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgrespassword"
    POSTGRES_DB: str = "resume_ranker"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    DATABASE_URL: str = ""

    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333

    # ── Embeddings ──────────────────────────────────────────────────
    EMBEDDING_PROVIDER: str = "local"
    EMBEDDING_MODEL_LOCAL: str = "paraphrase-multilingual-MiniLM-L12-v2"
    EMBEDDING_MODEL_OPENAI: str = "text-embedding-3-small"
    EMBEDDING_MODEL_VOYAGE: str = "voyage-multilingual-2"
    RERANKER_MODEL: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    OPENAI_API_KEY: str = ""
    VOYAGE_API_KEY: str = ""

    # ── LLM (OpenRouter) ────────────────────────────────────────────
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_MODEL: str = "deepseek/deepseek-v4-flash"
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    LLM_TIMEOUT_SECONDS: float = 90.0
    LLM_MAX_RETRIES: int = 3

    # ── App ─────────────────────────────────────────────────────────
    CORS_ORIGINS: str = "http://localhost:3100,http://127.0.0.1:3100,http://localhost:3000"
    PDF_STORAGE_DIR: str = ""
    OBSERVABILITY_PAYLOAD_LIMIT: int = 4000

    @property
    def database_url(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def cors_origins(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def pdf_dir(self) -> str:
        """Absolute path for stored PDFs — independent of the process CWD."""
        if self.PDF_STORAGE_DIR:
            return self.PDF_STORAGE_DIR
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "pdfs")


settings = Settings()
