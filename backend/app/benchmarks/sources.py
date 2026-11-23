import hashlib
import json
import re
import shutil
import time
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath
from urllib.parse import quote, urljoin, urlsplit

import httpx

from .catalog import MIB, Dataset

BLOB_HASHES = {
    "dataset/dev.json": "970f239f591c782b17df420c0d343b780737f3da",
    "dataset/private_test.json": "af7ef36c00f4d4d31c77d54512a01ba32bf7be92",
    "dataset/test.json": "59958c7c3bb3b21f4dff6bc912a0fe0ae710aee0",
    "dataset/train.json": "a6c2c5a60f9abe3fba5a793cc4d9e1dee2e09209",
    "dataset_raw/tatqa_dataset_dev.json": "48075c812af3fe6698b1d5cb50d9dbf358d52784",
    "dataset_raw/tatqa_dataset_train.json": "ec6a61be61ea7bb92c3278877e46e8488cc5203c",
    "dataset_raw/tatqa_dataset_test_gold.json": "3d5d3b691af572646ba9b1ac4d8f78c5dca09732",
    "data/financebench_document_information.jsonl": "decdfa948630f289d05cc0048417b3b9107cfb9f",
    "data/financebench_open_source.jsonl": "4aef1d43a443474ba193f158f2baf70550ff528d",
    "data.zip": "bde03381e2d9ef0043796f2722f7a87633887358",
}
SPLIT = re.compile(r"^(private_test|validation|train|valid|dev|test)(?:[-_].*)?$", re.I)
SHA = re.compile(r"[a-f0-9]{40}")
DATA_FORMATS = {"parquet", "jsonl", "json"}
HOSTS = {
    "raw.githubusercontent.com",
    "huggingface.co",
    "cdn-lfs.hf.co",
    "cdn-lfs-us-1.hf.co",
    "cdn-lfs-eu-1.hf.co",
    "cdn-lfs.huggingface.co",
    "cas-bridge.xethub.hf.co",
}


class SourceError(ValueError):
    pass


class RetryableSourceError(SourceError):
    pass


@dataclass(frozen=True)
class Asset:
    url: str
    format: str
    size: int | None = None
    checksum: str | None = None
    blob_hash: str | None = None


def approved(url: str):
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in HOSTS or parts.netloc != parts.hostname:
        raise SourceError("The download was redirected to an unapproved source host.")


def require_space(directory: Path, required: int):
    if shutil.disk_usage(directory).free < required + 32 * MIB:
        raise SourceError("There is insufficient free disk space for the selected split and local index.")


def download(asset: Asset, target: Path, limit: int, progress=lambda _received, _total: None):
    if limit <= 0 or (asset.size is not None and asset.size > limit):
        raise SourceError("The selected download exceeds the size limit.")
    for attempt in range(3):
        try:
            with httpx.Client(timeout=httpx.Timeout(30.0, connect=12.0), follow_redirects=False) as client:
                url = asset.url
                for _ in range(7):
                    approved(url)
                    with client.stream("GET", url) as response:
                        if response.is_redirect:
                            location = response.headers.get("location")
                            if not location:
                                raise SourceError("The publisher returned an incomplete redirect.")
                            url = urljoin(url, location)
                            continue
                        if response.status_code == 429 or response.status_code >= 500:
                            delay = response.headers.get("retry-after", "")
                            if delay.isdecimal() and int(delay) > 8:
                                raise SourceError(
                                    "The publisher requested a longer retry delay. Try again later."
                                )
                            raise RetryableSourceError(
                                "The publisher is rate-limiting or temporarily unavailable."
                            )
                        if response.status_code != 200:
                            raise SourceError(f"The publisher returned HTTP {response.status_code}.")
                        try:
                            announced = int(response.headers.get("content-length", ""))
                        except ValueError:
                            announced = None
                        declared = asset.size if asset.size is not None else announced
                        if declared is not None and declared > limit:
                            raise SourceError("The selected download exceeds the size limit.")
                        require_space(
                            target.parent, declared if declared is not None else min(limit, 64 * MIB)
                        )
                        digest = hashlib.sha256()
                        received = 0
                        mark = 0
                        with target.open("wb") as output:
                            for chunk in response.iter_bytes(128 * 1024):
                                received += len(chunk)
                                if received > limit:
                                    raise SourceError("The selected download exceeds the size limit.")
                                digest.update(chunk)
                                output.write(chunk)
                                if received - mark >= MIB:
                                    require_space(target.parent, min(limit - received, 8 * MIB))
                                    progress(received, declared)
                                    mark = received
                        if not received or (asset.size is not None and received != asset.size):
                            raise RetryableSourceError("The publisher returned an incomplete file.")
                        if asset.checksum and digest.hexdigest() != asset.checksum:
                            raise SourceError(
                                "The download does not match the publisher’s SHA-256 checksum."
                            )
                        if asset.blob_hash:
                            blob = hashlib.sha1(f"blob {received}\0".encode(), usedforsecurity=False)
                            with target.open("rb") as stream:
                                for chunk in iter(lambda: stream.read(MIB), b""):
                                    blob.update(chunk)
                            if blob.hexdigest() != asset.blob_hash:
                                raise SourceError(
                                    "The download does not match the pinned Git release blob."
                                )
                        progress(received, declared)
                        return {"bytes": received, "sha256": digest.hexdigest()}
                raise SourceError("The publisher returned too many download redirects.")
        except (httpx.TransportError, RetryableSourceError) as error:
            target.unlink(missing_ok=True)
            if attempt == 2:
                raise SourceError(
                    "Could not download from the publisher. Check network access and retry."
                ) from error
            time.sleep(0.5 * (2**attempt))
        except BaseException:
            target.unlink(missing_ok=True)
            raise


def unpack_split(source: Path, member: str, target: Path, limit: int):
    # Read one known member to a generated filename. Archive paths never become filesystem paths.
    with zipfile.ZipFile(source) as archive:
        matches = [entry for entry in archive.infolist() if entry.filename == member]
        if len(matches) != 1 or matches[0].is_dir() or matches[0].file_size > limit:
            raise SourceError(
                "The publisher archive lacks the expected split or exceeds the unpacking limit."
            )
        require_space(target.parent, matches[0].file_size)
        with archive.open(matches[0]) as compressed, target.open("wb") as output:
            total = 0
            for chunk in iter(lambda: compressed.read(128 * 1024), b""):
                total += len(chunk)
                if total > limit:
                    raise SourceError("The expanded split exceeds the unpacking limit.")
                output.write(chunk)


def github_asset(dataset: Dataset, relative: str):
    return Asset(dataset.raw(relative), relative.rsplit(".", 1)[-1], blob_hash=BLOB_HASHES[relative])


def hub_split_key(relative, card):
    for cfg in card.get("configs") or []:
        for source in cfg.get("data_files") or []:
            if not isinstance(source, dict) or not isinstance(source.get("split"), str):
                continue
            paths = source.get("path", [])
            if isinstance(paths, str):
                paths = [paths]
            if any(fnmatchcase(str(relative), pattern.removeprefix("./")) for pattern in paths):
                name = cfg.get("config_name", "default")
                return source["split"] if name == "default" else f"{name}.{source['split']}"
    match = SPLIT.fullmatch(relative.stem)
    parent = SPLIT.fullmatch(relative.parent.name)
    if match:
        split, prefix = match[1].lower(), relative.parent.parts
    elif parent:
        split, prefix = parent[1].lower(), relative.parent.parent.parts
    else:
        return None
    config = ".".join(part for part in prefix if part not in {"data", "default"})
    return f"{config}.{split}" if config else split


def hub_assets(dataset: Dataset, temporary: Path):
    base = f"https://huggingface.co/api/datasets/{dataset.hub}"
    for suffix in ("", "/revision/refs%2Fconvert%2Fparquet"):
        manifest_path = temporary / "hub-manifest.json"
        try:
            download(Asset(base + suffix + "?blobs=true", "json"), manifest_path, 4 * MIB)
        except SourceError:
            if not suffix:
                raise
            break
        with manifest_path.open(encoding="utf-8") as stream:
            manifest = json.load(stream)
        revision = manifest.get("sha")
        if not isinstance(revision, str) or not SHA.fullmatch(revision):
            raise SourceError("Hugging Face did not return a valid immutable release revision.")
        card = manifest.get("cardData") or {}
        groups = defaultdict(list)
        for item in manifest.get("siblings", []):
            relative = PurePosixPath(item.get("rfilename", ""))
            if relative.is_absolute() or ".." in relative.parts or not relative.name:
                continue
            fmt = relative.suffix.lower().removeprefix(".")
            if fmt not in DATA_FORMATS:
                continue
            key = hub_split_key(relative, card)
            if not key or not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", key):
                continue
            lfs = item.get("lfs") or {}
            digest = lfs.get("sha256") or lfs.get("oid")
            checksum = digest if isinstance(digest, str) and re.fullmatch(r"[a-f0-9]{64}", digest) else None
            blob = item.get("blobId")
            groups[key].append(
                Asset(
                    f"https://huggingface.co/datasets/{dataset.hub}/resolve/{revision}/{quote(str(relative))}",
                    fmt,
                    item.get("size"),
                    checksum=checksum,
                    blob_hash=blob if not lfs and isinstance(blob, str) and SHA.fullmatch(blob) else None,
                )
            )
        if groups:
            # Prefer published Parquet shards when a split also has a JSON representation.
            for key, entries in groups.items():
                formats = {asset.format for asset in entries}
                preferred = next(fmt for fmt in ("parquet", "jsonl", "json") if fmt in formats)
                groups[key] = sorted(
                    (asset for asset in entries if asset.format == preferred), key=lambda a: a.url
                )
            license_name = card.get("license")
            if isinstance(license_name, list):
                license_name = ", ".join(map(str, license_name))
            return revision, groups, license_name
    raise SourceError("The official Hub release has no discoverable JSON, JSONL, or Parquet splits.")
