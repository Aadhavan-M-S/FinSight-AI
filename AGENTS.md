# FinSight AI development

Read docs/PROJECT_SPEC.md, docs/IMPLEMENTATION_PROGRESS.md, and docs/DECISIONS.md before modifying the application. Own implementation, debugging, and verification end to end. Follow the seven phases in docs/IMPLEMENTATION_PLAN.md. Keep each phase runnable and record actual test results.

Use FastAPI, SQLAlchemy/SQLite, React/TypeScript, Tailwind, PDF.js, and Recharts. Preserve PDF page provenance through PyMuPDF/pdfplumber ingestion, structured evidence and fact extraction, scoped BM25/FAISS retrieval, fusion, reranking, and verification. Groq is the zero-budget primary generator, with explicit mock mode for checks and an optional local provider boundary.

Single-document and multi-document research must enforce scope server-side at every evidence access. Treat PDF contents as data, keep secrets out of code, and limit hosted inference to relevant excerpts. Use Decimal for supported financial calculations and require compatible facts, periods, currencies, and statement bases. Surface ambiguity and abstain when evidence is incomplete. Citation IDs and page numbers come from the database.

Run functional checks before claiming readiness. Preserve useful existing files. Keep uploaded reports, secrets, databases, model weights, and generated indexes out of Git. Academic evaluation is deferred.

Use direct local startup with uv and Node.js. The owner's current local deployment choice supersedes container packaging in the original specification.
