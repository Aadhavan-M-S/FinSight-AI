# Architecture decisions

- Trusted local, single-user deployment. The application binds to loopback in local development and uses a relative API prefix through Vite.
- SQLite owns source metadata and chat history. Each document has independent evidence and a separate dense index, so candidate selection begins within scope.
- A deterministic calculation engine is authoritative for financial arithmetic. Hosted generation receives a bounded evidence bundle.
- The hosted provider is Groq by default. Local verification can use an explicitly labeled mock and a separately configured lexical-only retrieval path.
