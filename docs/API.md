# REST API

The FastAPI OpenAPI document is served at /openapi.json and the interactive documentation at /docs. Routes below use the /api/v1 prefix.

| Area | Endpoints |
| --- | --- |
| Documents | POST /documents/upload, GET /documents, GET /documents/{id}, GET /documents/{id}/status, GET /documents/{id}/file, GET /documents/{id}/pages/{page}, POST /documents/{id}/reprocess, DELETE /documents/{id} |
| Chat | POST and GET /chat/sessions, GET/PATCH/DELETE /chat/sessions/{id}, GET /chat/sessions/{id}/messages, POST /chat/sessions/{id}/query |
| Search | POST /retrieval/search, GET /evidence/{id} |
| Financials | GET /companies, GET /companies/{id}/financials, POST /financials/compare, POST /financials/calculate |
| System | GET /health, GET /system/status |

Upload uses repeated multipart files fields and optional company and year overrides. It returns accepted document records and per-file errors. Check document status before querying. Single mode takes exactly one document and research mode takes at least two distinct document IDs. Search and financial analysis require explicit document IDs. The optional session_id evidence parameter verifies the active session scope.
