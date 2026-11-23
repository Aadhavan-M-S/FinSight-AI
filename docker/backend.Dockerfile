FROM ghcr.io/astral-sh/uv:0.10 AS uv
FROM python:3.12-slim
COPY --from=uv /uv /bin/uv
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export SSL_CERT_FILE=/run/secrets/proxy_ca; fi; \
    uv sync --locked --no-dev --group neural
COPY backend/app ./app
ENV FINSIGHT_DATA_DIR=/app/data HF_HOME=/app/data/huggingface HF_HUB_DISABLE_XET=1
CMD [".venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
