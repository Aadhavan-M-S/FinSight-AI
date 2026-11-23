# Retrieval

Search filters the requested document scope and metadata before constructing BM25 candidates. Each document has a FAISS inner-product index built from normalized Sentence Transformer vectors. SQL evidence ordered by stable evidence ID supplies the vector mapping. Querying validates the index version, embedding fingerprint, dimensions, and mapping length. FAISS candidate selection uses an ID selector within each authorized index.

Reciprocal rank fusion combines lexical and dense rankings. The cross-encoder reranks the fused candidates in hybrid mode. Related evidence comes from the same authorized table or page section. The planner uses bounded year and company retrieval passes and deduplicates excerpts before generation. Configure lexical-only mode explicitly for offline functional checks.
