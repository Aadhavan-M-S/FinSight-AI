# Implementation progress

## Phase 7 validation

The project started from an empty repository and is published on GitHub's main branch. The full supplied specification is preserved in PROJECT_SPEC.md. The application has a FastAPI and SQLite backend, a React and Tailwind UI, locked dependencies, and direct local startup. The owner chose to remove container packaging from the project.

### Implemented

- Multi-file PDF upload, observable and resumable ingestion, narrative and table evidence, reprocessing, deletion, and page previews.
- Server-scoped BM25, persistent per-document FAISS, reciprocal rank fusion, and a configurable cross-encoder. Evidence remains scoped during retrieval, related-context expansion, financial resolution, and citation verification.
- Structured facts, Decimal-based calculation inputs and outputs, source-linked fiscal comparisons, and abstention on conflicting or unsupported figures.
- Persistent document and research chats, bounded retrieval planning, follow-up topics, a Groq SDK integration, an explicit mock provider, and source quotation and numeric checks.
- Six workspace views with upload, research history, PDF.js citation navigation and highlighting, and Recharts comparisons.

### Verified

- Locked installation, Ruff and formatting, five pytest tests, Vite production build, and both FastAPI and Vite API startup checks.
- After removing container packaging, reran the locked install, Ruff, five backend tests, and the Vite build. Started both services directly on Linux with Groq configured as the provider and verified API health through Vite. The README also documents a two-terminal Windows setup.
- Public Apple and Microsoft FY2022 10-K smoke through the local Vite frontend and FastAPI. Verified ingestion, Apple FY2022 revenue on PDF page 32, a year-over-year follow-up, the two-company growth comparison, and retrieval scope.
- Headless Chromium against the initial release. Verified an upload request, chat, PDF.js rendering and citation highlight, page navigation, session reopening, chart, operating margin, and narrow-viewport navigation.
- Groq SDK model discovery, rate-limit retry, and structured response validation via HTTP test transport. FAISS persistence and scope filtering verified, with a separate test using local test weights through Sentence Transformers and the cross-encoder.

### Open verification

The running cloud policy blocks Hugging Face and Groq, and the backend has no Groq key. Production weights and live model inference still need verification. The environment draft contains an install script, startup instructions, network additions, and a secure GROQ_API_KEY requirement. The draft requires user review and publication. The current demo uses explicit lexical retrieval and the mock provider for qualitative answers.

OCR, optional Ollama, semantic claim verification, and formal finance benchmarking remain deferred. Financial table coverage is heuristic.

After the cloud settings are active, verify the model downloads and Groq model discovery, reprocess a report with dense indexing enabled, and check a qualitative query and source navigation with the live provider.
