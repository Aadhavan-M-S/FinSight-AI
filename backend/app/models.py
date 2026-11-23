from sqlalchemy import JSON, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base, now, uid


class Company(Base):
    __tablename__ = "companies"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String)
    normalized_name: Mapped[str] = mapped_column(String, unique=True)
    ticker: Mapped[str | None] = mapped_column(String)
    industry: Mapped[str | None] = mapped_column(String)
    country: Mapped[str | None] = mapped_column(String)


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    filename: Mapped[str] = mapped_column(String)
    digest: Mapped[str] = mapped_column(String, index=True)
    company_id: Mapped[str | None] = mapped_column(ForeignKey("companies.id"), index=True)
    company_name: Mapped[str | None] = mapped_column(String)
    year: Mapped[int | None] = mapped_column(Integer, index=True)
    report_type: Mapped[str] = mapped_column(String, default="annual_report")
    period: Mapped[str] = mapped_column(String, default="annual")
    source_url: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="pending", index=True)
    error: Mapped[str | None] = mapped_column(Text)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    extraction_version: Mapped[int] = mapped_column(Integer, default=0)
    page_sizes: Mapped[list] = mapped_column(JSON, default=list)
    scan_pages: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[str] = mapped_column(String, default=now)


class Evidence(Base):
    __tablename__ = "evidence"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    page: Mapped[int] = mapped_column(Integer)
    printed_page: Mapped[str | None] = mapped_column(String)
    section: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)
    text: Mapped[str] = mapped_column(Text)
    normalized: Mapped[str] = mapped_column(Text)
    table_id: Mapped[str | None] = mapped_column(String, index=True)
    structure: Mapped[dict] = mapped_column(JSON, default=dict)
    boxes: Mapped[list] = mapped_column(JSON, default=list)
    quality: Mapped[str] = mapped_column(String, default="extracted")


class Fact(Base):
    __tablename__ = "facts"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence.id", ondelete="CASCADE"), index=True)
    company_id: Mapped[str | None] = mapped_column(ForeignKey("companies.id"), index=True)
    label: Mapped[str] = mapped_column(String)
    metric: Mapped[str] = mapped_column(String, index=True)
    value: Mapped[str] = mapped_column(String)
    currency: Mapped[str | None] = mapped_column(String)
    unit: Mapped[str] = mapped_column(String)
    scale: Mapped[str] = mapped_column(String)
    year: Mapped[int] = mapped_column(Integer, index=True)
    period: Mapped[str] = mapped_column(String)
    period_start: Mapped[str | None] = mapped_column(String)
    period_end: Mapped[str | None] = mapped_column(String)
    basis: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="extracted")


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    stage: Mapped[str] = mapped_column(String, default="Queued")
    status: Mapped[str] = mapped_column(String, default="pending")
    progress: Mapped[float] = mapped_column(Float, default=0)
    started_at: Mapped[str | None] = mapped_column(String)
    completed_at: Mapped[str | None] = mapped_column(String)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String, default=now)


class ChatSession(Base):
    __tablename__ = "chat_sessions"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    title: Mapped[str] = mapped_column(String)
    mode: Mapped[str] = mapped_column(String)
    document_ids: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String, default=now)
    updated_at: Mapped[str] = mapped_column(String, default=now)


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    session_id: Mapped[str] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[str] = mapped_column(String, default=now)
