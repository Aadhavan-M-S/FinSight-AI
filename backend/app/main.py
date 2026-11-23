import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from urllib.parse import urlsplit

from fastapi import APIRouter, FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from . import models  # noqa: F401
from .chat import router as chat_router
from .config import settings
from .database import Base, engine
from .documents import resume_jobs
from .documents import router as documents_router
from .financial import router as financial_router
from .retrieval import router as retrieval_router


class LogFormatter(logging.Formatter):
    def format(self, record):
        import json

        return json.dumps(
            {
                "time": datetime.now(timezone.utc).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
        )


handler = logging.StreamHandler()
handler.setFormatter(LogFormatter())
logger = logging.getLogger("finsight")
logger.addHandler(handler)
logger.setLevel(logging.INFO)


@asynccontextmanager
async def lifespan(_app):
    Base.metadata.create_all(engine)
    resume_jobs()
    yield


app = FastAPI(title="FinSight AI", version="0.1.0", lifespan=lifespan)
api = APIRouter(prefix="/api/v1")


@app.middleware("http")
async def protect_local_workspace(request, call_next):
    if request.url.path.startswith("/api/") and request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        if origin and (
            request.headers.get("sec-fetch-site") == "cross-site"
            or urlsplit(origin).netloc != request.headers.get("host")
        ):
            return JSONResponse({"detail": "Cross-origin writes are disabled."}, status_code=403)
        if request.url.path == "/api/v1/documents/upload":
            size = request.headers.get("content-length")
            if size and size.isdecimal() and int(size) > (10 * settings.max_upload_mb + 1) * 1024 * 1024:
                return JSONResponse({"detail": "Upload exceeds the total size limit."}, status_code=413)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@api.get("/health")
def health():
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok"}


@api.get("/system/status")
def system_status():
    return {
        **health(),
        "provider": settings.llm_provider,
        "groq_key_configured": bool(settings.groq_api_key),
        "dense_retrieval": settings.dense_retrieval,
    }


api.include_router(documents_router)
api.include_router(financial_router)
api.include_router(retrieval_router)
api.include_router(chat_router)
app.include_router(api)
