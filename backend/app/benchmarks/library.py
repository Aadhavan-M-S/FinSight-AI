import hashlib
import logging
import sqlite3
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import RLock
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Query, Response, UploadFile
from ijson import JSONError
from pydantic import ValidationError

from .adapters import ADAPTERS, pdf_url, read_rows
from .catalog import CATALOG, MIB, MULTI_DOWNLOAD
from .schemas import InstallRequest
from .sources import Asset, SourceError, download, github_asset, hub_assets, require_space, unpack_split
from .store import ACTIVE_INSTALL, stage_records, store

logger = logging.getLogger("finsight.benchmarks")
router = APIRouter(prefix="/benchmarks", tags=["benchmarks"])
executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="benchmark-install")
jobs_lock = RLock()
Split = Annotated[str, Query(pattern=r"^[a-zA-Z0-9_.-]{1,80}$")]


def dataset_or_404(dataset_id):
    if dataset_id not in CATALOG:
        raise HTTPException(404, "Benchmark dataset is not supported.")
    return CATALOG[dataset_id]


def payload(dataset):
    installed = store.installed(dataset.id)
    job = store.job(dataset.id)
    state = job["state"] if job else ("ready" if installed else "not_installed")
    return {
        "id": dataset.id,
        "name": dataset.name,
        "description": dataset.description,
        "source": dataset.source,
        "citation": dataset.citation,
        "terms": dataset.terms,
        "terms_url": dataset.terms_url,
        "revision": dataset.revision,
        "splits": [{"id": key, "label": name} for key, name in dataset.splits.items()],
        "task_type": dataset.task_type,
        "tasks": dataset.tasks,
        "limitations": dataset.limits,
        "download_limit_bytes": dataset.max_download,
        "download_mode": "hub" if dataset.hub else "publisher" if dataset.files else "import",
        "import_url": MULTI_DOWNLOAD if dataset.id == "multihiertt" else dataset.source,
        "noncommercial": dataset.noncommercial,
        "state": state,
        "installations": installed,
        "job": job,
    }


def verify_split(dataset, split):
    if dataset.splits and split not in dataset.splits:
        raise HTTPException(422, "Choose a supported publisher split.")


def verify_available(dataset_id, split=None):
    job = store.job(dataset_id)
    if job and job["state"] in ACTIVE_INSTALL:
        raise HTTPException(409, "An installation is already in progress for this dataset.")
    with store.connect() as db:
        active = db.execute(
            """
            SELECT 1 FROM runs WHERE dataset_id=? AND (? IS NULL OR split=?)
            AND state IN ('queued','running') LIMIT 1
        """,
            (dataset_id, split, split),
        ).fetchone()
    if active:
        raise HTTPException(409, "Wait for the evaluation to finish or cancel it first.")


def verified_terms(dataset, accepted):
    if dataset.noncommercial and not accepted:
        raise HTTPException(422, "Confirm the publisher’s noncommercial usage restriction.")


def split_manifest(dataset, split, temporary):
    if dataset.hub:
        revision, groups, _ = hub_assets(dataset, temporary)
        if split not in groups:
            raise SourceError("The requested split is absent from the publisher release.")
        return revision, groups[split], None
    file = dataset.archive or dataset.files[split]
    assets = [github_asset(dataset, file)]
    if dataset.id == "financebench":
        assets.append(github_asset(dataset, "data/financebench_document_information.jsonl"))
    return dataset.revision, assets, dataset.files[split] if dataset.archive else None


def download_split(dataset, split, temporary):
    revision, assets, member = split_manifest(dataset, split, temporary)
    known_size = sum(a.size for a in assets) if all(a.size is not None for a in assets) else None
    if known_size and known_size > dataset.max_download:
        raise SourceError("This split exceeds the on-demand download limit.")
    require_space(temporary, min((known_size or 32 * MIB) * 3, dataset.max_download * 3))
    downloaded = 0
    artifacts, inputs = [], []
    for index, asset in enumerate(assets):
        target = temporary / f"asset-{index}.{asset.format}"

        def progress(received, total):
            expected = known_size or (total if len(assets) == 1 else None)
            total_received = downloaded + received
            ratio = min(0.8, 0.8 * total_received / expected) if expected else 0.1
            store.set_job(
                dataset.id,
                split,
                "downloading",
                ratio,
                "Downloading publisher data",
                total_received,
                expected,
            )

        artifact = download(asset, target, dataset.max_download - downloaded, progress)
        artifact["source_url"] = asset.url
        artifacts.append(artifact)
        downloaded += artifact["bytes"]
        inputs.append((target, asset.format))
    if member:
        unpacked = temporary / "split.json"
        unpack_split(inputs[0][0], member, unpacked, dataset.max_download)
        inputs = [(unpacked, "json")]
    return revision, inputs, artifacts


def install(dataset, split, incoming=None):
    directory = store.root / dataset.id
    try:
        directory.mkdir(exist_ok=True)
        with TemporaryDirectory(prefix=".install-", dir=directory) as scratch:
            temporary = Path(scratch)
            if incoming:
                path, fmt, artifact = incoming
                revision, inputs, artifacts = (
                    "local-import:" + artifact["sha256"],
                    [(path, fmt)],
                    [artifact],
                )
            else:
                revision, inputs, artifacts = download_split(dataset, split, temporary)
            size = sum(item["bytes"] for item in artifacts)
            store.set_job(
                dataset.id, split, "processing", 0.85, "Validating and indexing records", size, size
            )
            require_space(temporary, min(size * 3, dataset.max_download * 3))
            extras = {}
            if dataset.id == "financebench" and len(inputs) == 2:
                path, fmt = inputs.pop()
                extras = {row["doc_name"]: row for row in read_rows(path, fmt)}

            def records():
                for path, fmt in inputs:
                    for row in read_rows(path, fmt):
                        if not isinstance(row, dict):
                            raise ValueError("Expected an object for each publisher record.")
                        yield from ADAPTERS[dataset.id](dataset, split, row, extras)

            staged = temporary / "records.sqlite3"
            count = stage_records(staged, records())
            if dataset.id == "financebench" and not incoming and count != 150:
                raise SourceError(
                    "The public FinanceBench release did not contain the expected 150 records."
                )
            require_space(temporary, staged.stat().st_size * 2)
            store.swap(staged, dataset.id, split, revision, count, artifacts)
    except (
        ValueError,
        KeyError,
        TypeError,
        IndexError,
        JSONError,
        zipfile.BadZipFile,
        sqlite3.IntegrityError,
    ) as error:
        logger.warning("Install failed for %s/%s (%s)", dataset.id, split, type(error).__name__)
        message = (
            str(error)
            if isinstance(error, SourceError)
            else "The split failed publisher schema validation."
        )
        store.set_job(dataset.id, split, "failed", message=message)
    except Exception as error:
        logger.error("Install failed for %s/%s (%s)", dataset.id, split, type(error).__name__)
        store.set_job(
            dataset.id, split, "failed", message="Installation failed. Check available storage and retry."
        )
    finally:
        if incoming:
            incoming[0].unlink(missing_ok=True)


@router.get("")
def datasets():
    return [payload(dataset) for dataset in CATALOG.values()]


@router.get("/{dataset_id}")
@router.get("/{dataset_id}/status")
def dataset_status(dataset_id: str):
    return payload(dataset_or_404(dataset_id))


@router.get("/{dataset_id}/splits")
def discover_splits(dataset_id: str):
    dataset = dataset_or_404(dataset_id)
    if not dataset.hub:
        return {"splits": payload(dataset)["splits"], "revision": dataset.revision, "license": None}
    try:
        with TemporaryDirectory(prefix=".manifest-", dir=store.root) as scratch:
            revision, groups, license_name = hub_assets(dataset, Path(scratch))
    except (ValueError, OSError) as error:
        message = (
            str(error)
            if isinstance(error, SourceError)
            else "Could not read the publisher release metadata."
        )
        raise HTTPException(502, message) from error
    return {
        "revision": revision,
        "license": license_name,
        "splits": [
            {
                "id": key,
                "label": key,
                "bytes": sum(a.size for a in assets) if all(a.size is not None for a in assets) else None,
            }
            for key, assets in groups.items()
        ],
    }


@router.post("/{dataset_id}/install", status_code=202)
def install_endpoint(dataset_id: str, body: InstallRequest):
    dataset = dataset_or_404(dataset_id)
    verify_split(dataset, body.split)
    verified_terms(dataset, body.accept_restrictions)
    if not dataset.files and not dataset.hub:
        raise HTTPException(422, "Use the publisher’s download link, then import the official split file.")
    with jobs_lock:
        verify_available(dataset_id, body.split)
        store.set_job(dataset_id, body.split, "downloading", message="Queued")
        executor.submit(install, dataset, body.split)
    return dataset_status(dataset_id)


@router.post("/{dataset_id}/import", status_code=202)
def import_endpoint(
    dataset_id: str,
    file: UploadFile,
    split: Annotated[str, Form()],
    accept_restrictions: Annotated[bool, Form()] = False,
):
    from tempfile import NamedTemporaryFile

    dataset = dataset_or_404(dataset_id)
    try:
        body = InstallRequest(split=split, accept_restrictions=accept_restrictions)
    except ValidationError as error:
        raise HTTPException(422, "Choose a valid official split identifier.") from error
    verify_split(dataset, body.split)
    verified_terms(dataset, body.accept_restrictions)
    fmt = Path(file.filename or "").suffix.lower().removeprefix(".")
    if fmt not in {"json", "jsonl", "parquet"}:
        raise HTTPException(422, "Import an original JSON, JSONL, or Parquet split.")
    path = None
    try:
        size, digest = 0, hashlib.sha256()
        with NamedTemporaryFile(prefix=".import-", dir=store.root, delete=False) as target:
            path = Path(target.name)
            while chunk := file.file.read(128 * 1024):
                size += len(chunk)
                if size > dataset.max_download:
                    raise HTTPException(413, "The selected split exceeds the local import limit.")
                if size % (8 * MIB) == 0:
                    require_space(store.root, 8 * MIB)
                digest.update(chunk)
                target.write(chunk)
        if not size:
            raise HTTPException(422, "The split file is empty.")
        with jobs_lock:
            verify_available(dataset.id, split)
            store.set_job(dataset.id, split, "processing", message="Queued import")
            executor.submit(
                install, dataset, split, (path, fmt, {"sha256": digest.hexdigest(), "bytes": size})
            )
    except SourceError as error:
        if path:
            path.unlink(missing_ok=True)
        raise HTTPException(507, str(error)) from error
    except BaseException:
        if path:
            path.unlink(missing_ok=True)
        raise
    return dataset_status(dataset_id)


@router.delete("/{dataset_id}/installation", status_code=204)
def remove_installation(dataset_id: str, split: Split | None = None):
    dataset_or_404(dataset_id)
    with jobs_lock:
        verify_available(dataset_id, split)
        store.remove(dataset_id, split)


@router.get("/{dataset_id}/samples")
def samples(
    dataset_id: str,
    split: Split,
    q: str = Query("", max_length=200),
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
):
    dataset_or_404(dataset_id)
    if not store.installation(dataset_id, split):
        raise HTTPException(404, "Install the selected split before browsing it.")
    count, rows = store.samples(dataset_id, split, q, limit, offset)
    return {"items": rows, "total": count, "limit": limit, "offset": offset}


@router.get("/{dataset_id}/samples/{question_id:path}")
def sample(dataset_id: str, question_id: str, split: Split):
    dataset_or_404(dataset_id)
    item = store.sample(dataset_id, split, question_id)
    if item is None:
        raise HTTPException(404, "Benchmark question not found in this split.")
    return item


@router.get("/{dataset_id}/filings/{filing}")
def source_filing(dataset_id: str, filing: str, split: Split, question_id: str = Query(max_length=500)):
    dataset = dataset_or_404(dataset_id)
    record = store.sample(dataset_id, split, question_id)
    if (
        dataset_id != "financebench"
        or record is None
        or not any(item["id"] == filing for item in record.source.get("filings", []))
    ):
        raise HTTPException(404, "This publisher filing is not linked to the installed question.")
    try:
        with TemporaryDirectory(prefix=".filing-", dir=store.root) as scratch:
            target = Path(scratch) / "source.pdf"
            download(Asset(pdf_url(dataset, filing), "pdf"), target, 40 * MIB)
            with target.open("rb") as stream:
                if not stream.read(5).startswith(b"%PDF-"):
                    raise SourceError("The publisher response was not a PDF.")
                stream.seek(0)
                content = stream.read()
    except (SourceError, OSError) as error:
        message = str(error) if isinstance(error, SourceError) else "Could not read the publisher filing."
        raise HTTPException(502, message) from error
    return Response(
        content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'inline; filename="financebench-source.pdf"',
            "Cache-Control": "private, no-store",
        },
    )
