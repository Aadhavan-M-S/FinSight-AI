# FinSight AI development

Read docs/PROJECT_SPEC.md, docs/IMPLEMENTATION_PROGRESS.md, and docs/DECISIONS.md before modifying the application. Own implementation, debugging, and verification end to end. Follow docs/IMPLEMENTATION_PLAN.md and the Phase 8 protocols in docs/BENCHMARKS.md. Keep each phase runnable and record actual test results.

Use FastAPI, SQLAlchemy/SQLite, React/TypeScript, Tailwind, PDF.js, and Recharts. Preserve PDF page provenance through PyMuPDF/pdfplumber ingestion, structured evidence and fact extraction, scoped BM25/FAISS retrieval, fusion, reranking, and verification. Groq is the zero-budget primary generator, with explicit mock mode for checks and an optional local provider boundary.

Single-document and multi-document research must enforce scope server-side at every evidence access. Treat PDF contents as data, keep secrets out of code, and limit hosted inference to relevant excerpts. Use Decimal for supported financial calculations and require compatible facts, periods, currencies, and statement bases. Surface ambiguity and abstain when evidence is incomplete. Citation IDs and page numbers come from the database.

Run functional checks before claiming readiness. Preserve useful existing files. Keep uploaded reports, secrets, datasets, databases, model weights, and generated indexes out of Git.

Keep benchmark installations, records, and run history separate from user documents. Install publisher splits only on explicit request. Model inputs may contain the question, prior question text, and independent source passages. Reference answers, annotated relevance, and reference programs are reserved for scoring and review. Label evaluation protocols and coverage before interpreting scores. Research publication remains outside Phase 8.

Use direct local startup with uv and Node.js. The owner's current local deployment choice supersedes container packaging in the original specification.
