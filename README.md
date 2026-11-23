# FinSight AI

FinSight AI is a local financial research workspace for text-based PDF filings. Upload reports, chat with one document or a selected collection, inspect source pages, and compare supported financial figures across companies and fiscal years.

## Run locally

Use Python 3.12, uv, Node 22.12+ (or a newer supported version), and Bash 4.3+.

```bash
bash scripts/install.sh
bash scripts/dev.sh
```

Open the Vite application on loopback port 5173. FastAPI listens on loopback port 8000, with interactive API documentation at `/docs`. SQLite, PDF files, FAISS indexes, and model downloads are stored in ignored `data/` directories. Run a single backend process for this local deployment.

Groq is the default hosted generation provider. Set `GROQ_API_KEY` through the environment or a local, ignored `.env` file based on `.env.example`. The backend selects from supported candidates returned by Groq or checks the configured `GROQ_MODEL`. Selected excerpts may be sent to Groq for qualitative generation. Report parsing, evidence retrieval, and supported financial arithmetic run locally.

Dense retrieval downloads the configured BGE embedding and MiniLM reranker models from Hugging Face. Both models run on CPU. The first ingestion downloads the embedding model and the first qualitative query loads the reranker. Reprocess previous documents after switching from lexical mode or changing the embedding model.

For an explicit offline verification mode, set `DENSE_RETRIEVAL=false LLM_PROVIDER=mock` when launching. This uses BM25 plus deterministic financial calculations and visibly labeled source excerpts in the chat.

## Docker

```bash
docker compose up --build
```

The UI and API share port 5173 and data persists in the Compose volume. In Codex Cloud, include `-f compose.yaml -f docker/compose.cloud.yaml` to supply the cloud CA via build and runtime mounts.

## Verify

```bash
cd backend
.venv/bin/ruff check app tests
OMP_NUM_THREADS=2 .venv/bin/pytest -q
cd ../frontend
npm run build
```

For a representative two-report smoke check, use the public Apple and Microsoft FY2022 10-K PDFs from the [FinanceBench filing archive](https://github.com/patronus-ai/financebench/tree/main/pdfs). The smoke runner takes paths in Apple, Microsoft order and supports `--url` for a separate test instance. Run it against an isolated database because it creates test sessions. The reports are independent functional fixtures. Formal evaluation is deferred.

```bash
backend/.venv/bin/python scripts/smoke.py /path/to/APPLE_2022_10K.pdf /path/to/MICROSOFT_2022_10K.pdf
```

## Scope and limits

This build is intended for trusted single-user local use. Adding accounts and document-level user authorization would be required before hosting this application for multiple users. Table parsing is heuristic and returns source excerpts for inspection. Scanned pages without extractable text are flagged. OCR and Ollama are deferred. Qualitative verification checks evidence IDs, page references, source quotations, and quoted numbers. Semantic entailment and formal finance benchmark evaluation are deferred.

See [architecture](docs/ARCHITECTURE.md), [API surface](docs/API.md), and [implementation progress](docs/IMPLEMENTATION_PROGRESS.md).
