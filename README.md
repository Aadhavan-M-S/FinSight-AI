# FinSight AI

FinSight AI is a local financial research workspace for text-based PDF filings. Upload reports, chat with one document or a selected collection, inspect source pages, and compare supported financial figures across companies and fiscal years.

## Run locally

Install Python 3.12, uv, and Node.js 22.12 or later. From the project folder, copy `.env.example` to `.env` and set `GROQ_API_KEY` to your [Groq API key](https://console.groq.com/keys). Keep the key in the local `.env` file.

### macOS or Linux with Bash 4.3+

```bash
bash scripts/install.sh
bash scripts/dev.sh
```

### Windows PowerShell

In one terminal, from the project folder, install and start the backend.

```powershell
cd backend
uv sync --locked --group neural --python 3.12
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In a second terminal, from the project folder, install and start the frontend.

```powershell
cd frontend
npm.cmd ci
npm.cmd run dev -- --host 127.0.0.1
```

On macOS with the system Bash, you can also use two terminals. From `backend/`, run `uv sync --locked --group neural --python 3.12`, then `.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`. From `frontend/`, run `npm ci`, then `npm run dev -- --host 127.0.0.1`.

Once both services are running, open [localhost:5173](http://localhost:5173). Upload a text-based annual report in **Document library**, wait for **Ready**, and open **Document chat**. A question about the report's disclosed risks exercises Groq generation.

FastAPI listens on loopback port 8000, with interactive API documentation at `/docs`. SQLite, PDF files, and FAISS indexes are stored in the ignored `data/` directory by default. Run a single backend process for this local deployment.

Groq is the default hosted generation provider. Set `GROQ_API_KEY` through the environment or a local, ignored `.env` file based on `.env.example`. The backend selects from supported candidates returned by Groq or checks the configured `GROQ_MODEL`. Selected excerpts may be sent to Groq for qualitative generation. Report parsing, evidence retrieval, and supported financial arithmetic run locally.

Dense retrieval downloads the configured BGE embedding and MiniLM reranker models from Hugging Face. Both models run on CPU. The first ingestion downloads the embedding model and the first qualitative query loads the reranker. To start with keyword search and keep Groq generation, set `DENSE_RETRIEVAL=false` in `.env`. Reprocess previous documents after switching from lexical mode to dense retrieval or changing the embedding model.

For an explicit offline verification mode, set `DENSE_RETRIEVAL=false LLM_PROVIDER=mock` when launching. This uses BM25 plus deterministic financial calculations and visibly labeled source excerpts in the chat.

## Benchmark Library

After pulling Phase 8, rerun the locked backend installation and restart both services. Open **Benchmark Library**, choose a dataset, and install one publisher split or import its original file. Download size limits, source terms, and split availability appear with each dataset. Benchmark records and saved evaluations are stored under `data/benchmarks/`.

Select **Run evaluation** within an installed split. BM25 retrieval runs work locally without an API key. Supported numerical and QA tasks use your configured Groq key, with a small request budget. Open **Evaluation runs** to inspect evidence, predictions, references, and export JSON or CSV. [Dataset details and evaluation protocols](docs/BENCHMARKS.md)

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
