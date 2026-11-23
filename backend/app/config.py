from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    finsight_data_dir: Path = ROOT / "data"
    llm_provider: str = "groq"
    groq_api_key: str = ""
    groq_model: str = ""
    groq_timeout_seconds: float = Field(40, gt=0, le=120)
    groq_max_retries: int = Field(2, ge=0, le=4)
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    dense_retrieval: bool = True
    max_upload_mb: int = Field(40, ge=1, le=250)
    max_pdf_pages: int = Field(600, ge=1, le=3000)
    chunk_chars: int = Field(1500, ge=250, le=5000)
    chunk_strategy: str = "section"
    rrf_constant: int = Field(60, ge=1)
    evidence_budget_chars: int = Field(16000, ge=1000, le=50000)
    candidate_count: int = Field(24, ge=4, le=100)

    @field_validator("finsight_data_dir", mode="before")
    @classmethod
    def default_directory(cls, value):
        return value or ROOT / "data"

    @field_validator("chunk_strategy")
    @classmethod
    def valid_chunk_strategy(cls, value):
        if value not in {"fixed", "paragraph", "section"}:
            raise ValueError("Choose fixed, paragraph, or section")
        return value


settings = Settings()
