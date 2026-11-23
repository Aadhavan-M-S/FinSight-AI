import hashlib
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from pathlib import Path
from threading import RLock

import pymupdf
from fastapi import APIRouter, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import delete, select

from .config import settings
from .database import Session, data_dir, now, transaction, uid
from .extraction import extract
from .models import Company, Document, Evidence, IngestionJob

router = APIRouter(prefix="/documents", tags=["documents"])
logger = logging.getLogger("finsight.ingestion")
executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ingestion")
mutation_lock = RLock()
busy = {"pending", "processing"}
uploads_dir = data_dir / "uploads"
uploads_dir.mkdir(exist_ok=True)


def pdf_path(document_id):
    return uploads_dir / f"{document_id}.pdf"


def get_document(db, identifier):
    document = db.get(Document, identifier)
    if document is None:
        raise HTTPException(404, "Document not found")
    return document


def latest(db, identifier):
    return db.scalar(
        select(IngestionJob)
        .where(IngestionJob.document_id == identifier)
        .order_by(IngestionJob.created_at.desc())
        .limit(1)
    )


def document_data(document, job=None):
    return {
        "id": document.id,
        "filename": document.filename,
        "company_id": document.company_id,
        "company_name": document.company_name,
        "year": document.year,
        "report_type": document.report_type,
        "period": document.period,
        "status": document.status,
        "error": document.error,
        "page_count": document.page_count,
        "scan_pages": document.scan_pages,
        "created_at": document.created_at,
        "progress": job.progress if job else 0,
        "stage": job.stage if job else None,
    }


def progress(job_id, value, stage):
    with transaction() as db:
        job = db.get(IngestionJob, job_id)
        job.stage, job.progress = stage, value


def ingest(document_id, job_id):
    from .financial import extract_facts
    from .retrieval import build_index, clean_indexes

    version = None
    try:
        with transaction() as db:
            document = db.get(Document, document_id)
            job = db.get(IngestionJob, job_id)
            document.status = job.status = "processing"
            job.started_at, job.stage = now(), "Reading PDF"
            filename = document.filename
            version = document.extraction_version + 1
        company_name, year, sizes, scans, evidence = extract(
            pdf_path(document_id),
            document_id,
            filename,
            lambda value, stage: progress(job_id, value, stage),
        )
        progress(job_id, 0.8, "Building search index")
        build_index(document_id, version, evidence)
        with transaction() as db:
            document = db.get(Document, document_id)
            job = db.get(IngestionJob, job_id)
            name = document.company_name or company_name
            if name:
                normalized = " ".join(name.casefold().split()).rstrip(".")
                company = db.scalar(select(Company).where(Company.normalized_name == normalized))
                if not company:
                    company = Company(name=name, normalized_name=normalized)
                    db.add(company)
                    db.flush()
                document.company_id, document.company_name = company.id, company.name
            document.year = document.year or year
            db.execute(delete(Evidence).where(Evidence.document_id == document_id))
            db.add_all(Evidence(**item) for item in evidence)
            db.flush()
            db.add_all(extract_facts(document, evidence))
            document.page_count, document.page_sizes, document.scan_pages = len(sizes), sizes, scans
            document.status, document.error, document.extraction_version = "completed", None, version
            job.status, job.stage, job.progress, job.completed_at = "completed", "Ready", 1, now()
        with suppress(OSError):
            clean_indexes(document_id, keep=version)
    except Exception as error:
        logger.error("Ingestion failed for %s (%s)", document_id, type(error).__name__)
        message = (
            str(error)
            if isinstance(error, ValueError)
            else "Processing failed. Check the backend logs and retry."
        )
        with transaction() as db:
            document = db.get(Document, document_id)
            job = db.get(IngestionJob, job_id)
            document.status, document.error = "failed", message
            job.status, job.stage, job.error, job.completed_at = "failed", "Failed", message, now()
        if version is not None:
            with suppress(OSError):
                clean_indexes(document_id, only=version)


def resume_jobs():
    with transaction() as db:
        queued = []
        for document in db.scalars(select(Document).where(Document.status.in_(busy))):
            job = latest(db, document.id)
            if job:
                document.status = job.status = "pending"
                job.stage, job.progress = "Queued after restart", 0
                queued.append((document.id, job.id))
    for ids in queued:
        executor.submit(ingest, *ids)


def clean_filename(raw):
    return re.sub(r"[\x00-\x1f\x7f]", "", Path((raw or "report.pdf").replace("\\", "/")).name)[:240]


@router.post("/upload", status_code=202)
def upload(
    files: list[UploadFile],
    company: str | None = Form(None, max_length=120),
    year: int | None = Form(None, ge=1900, le=2100),
):
    if not 1 <= len(files) <= 10:
        raise HTTPException(400, "Choose one to ten PDFs per upload.")
    results, errors = [], []
    for file in files:
        filename, identifier = clean_filename(file.filename), uid()
        path = pdf_path(identifier)
        digest = hashlib.sha256()
        size = 0
        try:
            if not filename.lower().endswith(".pdf"):
                raise ValueError("Only PDF files are supported.")
            with path.open("xb") as output:
                while chunk := file.file.read(1024 * 1024):
                    if not size and not chunk.startswith(b"%PDF-"):
                        raise ValueError("The file does not have a PDF header.")
                    size += len(chunk)
                    if size > settings.max_upload_mb * 1024 * 1024:
                        raise ValueError(f"PDF exceeds the {settings.max_upload_mb} MB limit.")
                    digest.update(chunk)
                    output.write(chunk)
            try:
                with pymupdf.open(path) as pdf:
                    if not pdf.is_pdf or pdf.needs_pass or not 0 < len(pdf) <= settings.max_pdf_pages:
                        raise ValueError("Use an unencrypted PDF within the page limit.")
            except pymupdf.FileDataError as exc:
                raise ValueError("The PDF could not be opened.") from exc
            with mutation_lock:
                with transaction() as db:
                    previous = (
                        db.scalar(
                            select(Document).where(
                                Document.digest == digest.hexdigest(),
                                Document.company_name == (company or None),
                            )
                        )
                        if company
                        else db.scalar(select(Document).where(Document.digest == digest.hexdigest()))
                    )
                    if previous and (year is None or previous.year == year):
                        results.append(document_data(previous, latest(db, previous.id)))
                        path.unlink()
                        continue
                    document = Document(
                        id=identifier,
                        filename=filename,
                        digest=digest.hexdigest(),
                        company_name=company.strip() if company else None,
                        year=year,
                    )
                    job = IngestionJob(document_id=identifier)
                    db.add(document)
                    db.flush()
                    db.add(job)
                    db.flush()
                    results.append(document_data(document, job))
                executor.submit(ingest, identifier, job.id)
        except ValueError as error:
            path.unlink(missing_ok=True)
            errors.append({"filename": filename, "message": str(error)})
        except Exception:
            path.unlink(missing_ok=True)
            raise
    return {"documents": results, "errors": errors}


@router.get("")
def list_documents():
    with Session() as db:
        return [
            document_data(item, latest(db, item.id))
            for item in db.scalars(select(Document).order_by(Document.created_at.desc()))
        ]


@router.get("/{identifier}")
@router.get("/{identifier}/status")
def document_status(identifier: str):
    with Session() as db:
        return document_data(get_document(db, identifier), latest(db, identifier))


@router.get("/{identifier}/file")
def original_pdf(identifier: str):
    with Session() as db:
        document = get_document(db, identifier)
        path = pdf_path(document.id)
        if not path.is_file():
            raise HTTPException(404, "Original PDF is unavailable")
        return FileResponse(
            path,
            media_type="application/pdf",
            filename=document.filename,
            content_disposition_type="inline",
            headers={"Cache-Control": "private, no-store"},
        )


@router.get("/{identifier}/pages/{page}")
def page_evidence(identifier: str, page: int):
    from .retrieval import serialize_evidence

    with Session() as db:
        document = get_document(db, identifier)
        if not 1 <= page <= document.page_count:
            raise HTTPException(404, "Page not found")
        items = db.scalars(
            select(Evidence).where(Evidence.document_id == document.id, Evidence.page == page)
        )
        return {"page": page, "evidence": [serialize_evidence(item, document) for item in items]}


@router.post("/{identifier}/reprocess", status_code=202)
def reprocess(identifier: str):
    with mutation_lock:
        with transaction() as db:
            document = get_document(db, identifier)
            if document.status in busy:
                raise HTTPException(409, "Document is already queued for processing.")
            document.status, document.error = "pending", None
            job = IngestionJob(document_id=document.id)
            db.add(job)
            db.flush()
            payload = document_data(document, job)
        executor.submit(ingest, identifier, job.id)
        return payload


@router.delete("/{identifier}", status_code=204)
def delete_document(identifier: str):
    from .retrieval import clean_indexes

    with mutation_lock:
        with transaction() as db:
            document = get_document(db, identifier)
            if document.status in busy:
                raise HTTPException(409, "Wait for processing to finish before deleting this document.")
            db.delete(document)
        pdf_path(identifier).unlink(missing_ok=True)
        clean_indexes(identifier)
