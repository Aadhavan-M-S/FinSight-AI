from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class Passage(BaseModel):
    id: str
    text: str = Field(min_length=1)
    kind: Literal["text", "table", "pdf_page"] = "text"
    document: str | None = None
    page_index: int | None = Field(default=None, ge=0)


class Record(BaseModel):
    dataset_id: str
    question_id: str = Field(min_length=1, max_length=500)
    split: str
    question: str = Field(min_length=1, max_length=20000)
    gold_answer: Any = None
    answer_type: str | None = None
    context: list[Passage] = Field(default_factory=list)
    evidence: list[Passage] = Field(default_factory=list)
    relevant_ids: list[str] = Field(default_factory=list)
    source: dict = Field(default_factory=dict)
    tables: list = Field(default_factory=list)
    program: Any = None
    metadata: dict = Field(default_factory=dict)
    previous_questions: list[str] = Field(default_factory=list)

    @field_validator("question")
    @classmethod
    def strip_question(cls, value):
        if not value.strip():
            raise ValueError("A benchmark question cannot be blank.")
        return value.strip()


class InstallRequest(BaseModel):
    split: str = Field(pattern=r"^[a-zA-Z0-9_.-]{1,80}$")
    accept_restrictions: bool = False


class RunRequest(BaseModel):
    dataset_id: str = Field(pattern=r"^[a-z]+$")
    split: str = Field(pattern=r"^[a-zA-Z0-9_.-]{1,80}$")
    task: Literal["retrieval", "numerical", "qa"]
    limit: int = Field(default=5, ge=1, le=100)
    top_k: int = Field(default=5, ge=1, le=20)
    retrieval: Literal["bm25", "hybrid"] = "bm25"
    provider: Literal["groq"] | None = None


class Finding(BaseModel):
    question_id: str
    question: str
    state: Literal["scored", "unanswered", "failed", "unscored"]
    gold_answer: Any = None
    prediction: Any = None
    retrieved: list[Passage] = Field(default_factory=list)
    attributed_ids: list[str] = Field(default_factory=list)
    relevant_ids: list[str] = Field(default_factory=list)
    metrics: dict[str, float] = Field(default_factory=dict)
    error: str | None = None
    error_category: str | None = None
