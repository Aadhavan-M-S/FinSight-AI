import re
import time
from functools import lru_cache
from pathlib import Path
from threading import RLock
from uuid import uuid4

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from rank_bm25 import BM25Okapi
from sqlalchemy import select

from .config import settings
from .database import Session, data_dir
from .models import Document, Evidence

router = APIRouter(tags=["retrieval"])
index_dir = data_dir / "indexes"
index_dir.mkdir(exist_ok=True)
models_lock = RLock()
_failed_model_loads: dict[str, float] = {}
IDENTIFIER = re.compile(r"[0-9a-f-]{36}")


@lru_cache(maxsize=1)
def embedding_model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(settings.embedding_model, device="cpu", trust_remote_code=False)


@lru_cache(maxsize=1)
def reranker_model():
    from sentence_transformers import CrossEncoder

    return CrossEncoder(settings.reranker_model, device="cpu", trust_remote_code=False)


def neural_model(loader):
    name = loader.__name__
    if time.monotonic() - _failed_model_loads.get(name, -1000) < 60:
        raise ValueError("The retrieval model is unavailable. Check model access and retry in one minute.")
    try:
        return loader()
    except Exception as error:
        _failed_model_loads[name] = time.monotonic()
        raise ValueError(
            "The retrieval model could not load. Check neural dependencies and model access."
        ) from error


def index_path(document_id, version) -> Path:
    return index_dir / f"{document_id}.{version}.faiss"


def build_index(document_id, version, evidence):
    if not settings.dense_retrieval:
        return
    try:
        import faiss
    except ImportError as error:
        raise ValueError(
            "Install the neural dependency group or explicitly enable lexical-only retrieval."
        ) from error
    from .extraction import stable

    with models_lock:
        model = neural_model(embedding_model)
        vectors = model.encode(
            [item["normalized"] for item in sorted(evidence, key=lambda item: item["id"])],
            batch_size=32,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
    index = faiss.IndexFlatIP(vectors.shape[1])
    index.add(np.ascontiguousarray(vectors, dtype=np.float32))
    target = index_path(document_id, version)
    temporary = target.with_suffix(f".{uuid4()}.tmp")
    try:
        faiss.write_index(index, str(temporary))
        temporary.replace(target)
        target.with_suffix(".model").write_text(stable(settings.embedding_model), encoding="ascii")
    finally:
        temporary.unlink(missing_ok=True)


@lru_cache(maxsize=24)
def load_index(path, fingerprint):
    import faiss

    return faiss.read_index(str(path))


def clean_indexes(document_id, keep=None, only=None):
    if not IDENTIFIER.fullmatch(document_id):
        return
    for path in index_dir.glob(f"{document_id}.*"):
        version = path.name.split(".")[1]
        if (keep is None or version != str(keep)) and (only is None or version == str(only)):
            path.unlink(missing_ok=True)


def tokens(text):
    return re.findall(r"\w+(?:[.'’-]\w+)*", text.casefold())


def lexical_ranking(query, passages, limit):
    query_tokens = tokens(query)
    if not passages or not query_tokens:
        return []
    identifiers = list(passages)
    corpus = [tokens(text) for text in passages.values()]
    if not any(corpus):
        return []
    scores = BM25Okapi(corpus).get_scores(query_tokens)
    words = set(query_tokens)
    return [
        identifiers[i]
        for i in sorted(range(len(identifiers)), key=lambda i: (-scores[i], identifiers[i]))
        if words.intersection(corpus[i])
    ][:limit]


def serialize_evidence(item, document):
    return {
        "id": item.id,
        "document_id": item.document_id,
        "document_name": document.filename,
        "page": item.page,
        "printed_page": item.printed_page,
        "section": item.section,
        "kind": item.kind,
        "text": item.text,
        "boxes": item.boxes,
        "page_size": document.page_sizes[item.page - 1]
        if 0 < item.page <= len(document.page_sizes)
        else None,
        "structure": item.structure or {},
        "quality": item.quality,
    }


def scoped_documents(db, document_ids):
    if not document_ids or len(document_ids) != len(set(document_ids)):
        raise HTTPException(400, "Select a nonempty list of distinct documents.")
    documents = {
        item.id: item for item in db.scalars(select(Document).where(Document.id.in_(document_ids)))
    }
    if len(documents) != len(document_ids):
        raise HTTPException(404, "A selected document does not exist.")
    if any(document.status != "completed" for document in documents.values()):
        raise HTTPException(409, "Selected documents must be ready before you can query them.")
    return documents


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=3000)
    document_ids: list[str] = Field(min_length=1, max_length=30)
    top_k: int = Field(default=8, ge=1, le=20)
    company_id: str | None = None
    year: int | None = None
    report_type: str | None = None
    section: str | None = None
    basis: str | None = None
    kind: str | None = None


def reciprocal_rank_fusion(*rankings, constant):
    scores = {}
    for ranking in rankings:
        for position, identifier in enumerate(ranking, 1):
            scores[identifier] = scores.get(identifier, 0) + 1 / (constant + position)
    return sorted(scores, key=lambda item: (-scores[item], item))


def dense_ranking(query, documents, all_items, eligible, limit):
    import faiss

    from .extraction import stable

    with models_lock:
        model = neural_model(embedding_model)
        prompt = (
            "Represent this sentence for searching relevant passages: "
            if "bge-" in settings.embedding_model
            else ""
        )
        query_vector = np.ascontiguousarray(
            model.encode([prompt + query], normalize_embeddings=True), dtype=np.float32
        )
    scores = []
    for identifier, document in documents.items():
        bucket = [item for item in all_items if item.document_id == identifier]
        if not bucket:
            continue
        path = index_path(identifier, document.extraction_version)
        fingerprint = stable(settings.embedding_model)
        if not path.exists() or not path.with_suffix(".model").exists():
            raise HTTPException(409, "Reprocess selected documents to build their dense indexes.")
        if path.with_suffix(".model").read_text(encoding="ascii") != fingerprint:
            raise HTTPException(409, "Reprocess selected documents after changing the embedding model.")
        try:
            index = load_index(path, path.stat().st_mtime_ns)
        except RuntimeError as error:
            raise HTTPException(
                409, "A dense index could not be loaded. Reprocess the document."
            ) from error
        if index.ntotal != len(bucket) or index.d != query_vector.shape[1]:
            raise HTTPException(409, "A dense index needs reprocessing.")
        positions = np.asarray([i for i, item in enumerate(bucket) if item.id in eligible], dtype=np.int64)
        if not len(positions):
            continue
        params = faiss.SearchParameters(sel=faiss.IDSelectorBatch(positions))
        similarities, indices = index.search(query_vector, min(limit, len(positions)), params=params)
        scores.extend(
            (float(score), bucket[i].id) for score, i in zip(similarities[0], indices[0]) if i >= 0
        )
    return [identifier for _, identifier in sorted(scores, key=lambda pair: (-pair[0], pair[1]))[:limit]]


def search(db, request: SearchRequest):
    documents = scoped_documents(db, request.document_ids)
    documents = {
        key: doc
        for key, doc in documents.items()
        if (
            (request.company_id is None or request.company_id == doc.company_id)
            and (request.year is None or request.year == doc.year)
            and (request.report_type is None or request.report_type == doc.report_type)
        )
    }
    all_items = list(
        db.scalars(select(Evidence).where(Evidence.document_id.in_(documents)).order_by(Evidence.id))
    )
    candidates = {
        item.id: item
        for item in all_items
        if (
            (request.kind is None or request.kind == item.kind)
            and (request.section is None or request.section.casefold() in item.section.casefold())
            and (request.basis is None or request.basis == item.structure.get("basis"))
        )
    }
    if not candidates or not tokens(request.query):
        return []
    limit = max(request.top_k, settings.candidate_count)
    lexical = lexical_ranking(
        request.query, {identifier: item.normalized for identifier, item in candidates.items()}, limit
    )
    dense = []
    if settings.dense_retrieval:
        try:
            dense = dense_ranking(request.query, documents, all_items, candidates, limit)
        except (ImportError, ValueError) as error:
            raise HTTPException(
                503, "Dense retrieval is unavailable. Check the configured model and dependencies."
            ) from error
    ranked = reciprocal_rank_fusion(lexical, dense, constant=settings.rrf_constant)[:limit]
    if ranked and settings.dense_retrieval:
        try:
            with models_lock:
                model = neural_model(reranker_model)
                relevance = model.predict(
                    [(request.query, candidates[key].normalized) for key in ranked], show_progress_bar=False
                )
            ranked = [key for key, _ in sorted(zip(ranked, relevance), key=lambda pair: -float(pair[1]))]
        except (ImportError, ValueError) as error:
            raise HTTPException(503, "The cross-encoder is unavailable. Check model access.") from error
    hits = {}
    for identifier in ranked[: request.top_k]:
        item = candidates[identifier]
        result = serialize_evidence(item, documents[item.document_id])
        related = [
            other
            for other in all_items
            if other.id in candidates
            and other.id != identifier
            and other.document_id == item.document_id
            and other.page == item.page
            and (
                (item.table_id and other.table_id == item.table_id)
                or (item.section and other.section == item.section)
            )
        ]
        result["context"] = [
            serialize_evidence(other, documents[item.document_id]) for other in related[:2]
        ]
        hits[identifier] = result
    return list(hits.values())


@router.post("/retrieval/search")
def search_endpoint(request: SearchRequest):
    with Session() as db:
        return {"results": search(db, request), "mode": "hybrid" if settings.dense_retrieval else "lexical"}


@router.get("/evidence/{identifier}")
def evidence_endpoint(identifier: str, session_id: str | None = None):
    from .models import ChatSession

    with Session() as db:
        item = db.get(Evidence, identifier)
        document = db.get(Document, item.document_id) if item else None
        if session_id:
            session = db.get(ChatSession, session_id)
            if not session or not item or item.document_id not in session.document_ids:
                raise HTTPException(404, "Evidence is outside this session's current scope.")
        if not document or document.status != "completed" or not 1 <= item.page <= document.page_count:
            raise HTTPException(404, "Evidence is unavailable.")
        return serialize_evidence(item, document)
