# Architecture

React and Vite serve the local workspace, with FastAPI mounted under /api/v1. Vite proxies API requests from the frontend origin to the local backend. SQLAlchemy and SQLite store documents, company metadata, evidence, financial facts, ingestion jobs, and chat history. A single worker processes persistent ingestion jobs. The service resumes incomplete jobs after restart.

See [ingestion](DATA_PIPELINE.md), [retrieval](RETRIEVAL.md), and [financial reasoning](FINANCIAL_REASONING.md) for invariants and limitations. The querying flow resolves the session's server-side scope, plans a bounded lookup, validates calculation outputs or provider claims, and stores the original evidence snapshot with the message. Historical messages provide conversation topics and preserve provenance. New factual claims always require evidence from the current selected scope.
