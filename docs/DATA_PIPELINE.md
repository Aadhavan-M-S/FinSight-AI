# Data pipeline

The upload endpoint checks headers, file size, encryption, and page count, then stores content under a generated identifier. SHA-256 helps recognize repeated uploads. A background job records stages and progress.

PyMuPDF extracts positioned page blocks and layout text. pdfplumber reads ruled tables. A layout-based parser recovers fiscal columns from select borderless tables. Evidence records retain page, text, structure, and boxes when available. Section, paragraph, and fixed-length text chunking are configured by environment. Table metadata retains labels, fiscal columns, units, and nearby footnotes when detected. PDF page indexes are one-based.

Reprocessing creates a versioned index before replacing the associated SQL rows in one transaction. Evidence identifiers are derived from document, page, position, and content. Deletion cascades facts and evidence and removes files and indexes. Stored chat messages retain their source attribution. Mixed scanned reports surface a page warning and wholly scanned reports require user-provided OCR.
