# Benchmark Library

Choose **Benchmark Library** in the sidebar, open a dataset, and select a publisher split. **Install split** downloads the release files for that split. For Hub datasets, use **Discover official splits** first to see the release revision and any publisher-reported file sizes. **Import a publisher file** accepts original JSON, JSONL, or Parquet exports. Local imports record their SHA-256 digest and the split you select. Use files from the stated publisher so the selected split corresponds to its original partition.

No dataset downloads occur at startup. The library is separate from **Document library**. Its SQLite records and saved evaluations live under `data/benchmarks/` by default, with temporary downloads isolated in that directory. A split is ready after its records pass validation and the index commits. A failed reinstall keeps the previous installation. Removal deletes that split's records without deleting past run results. Interrupted jobs keep their last committed data and can be retried.

## Releases and terms

| Dataset | Release and terms | Local workflow |
| --- | --- | --- |
| FinDER | [Publisher card](https://huggingface.co/datasets/Linq-AI-Research/FinDER). Review the current terms and citation on the card. | Discover and install a Hub split or import an export. Review annotated evidence and reference answers. Evaluation needs an independently published retrieval corpus. |
| FinanceBench | [Publisher card](https://huggingface.co/datasets/PatronusAI/financebench) and [official filing repository](https://github.com/patronus-ai/financebench). Noncommercial use. Filing rights may be separate. | Install the 150-question `open_source` release. Open in-context publisher PDFs by page, or run PDF retrieval and QA tasks. |
| FinQA | [Official repository](https://github.com/czyssrs/FinQA) with MIT license file and [paper](https://arxiv.org/abs/2109.00122). | Install an official split and browse table rows, surrounding text, gold indices, and reference programs. Private test references are unavailable. |
| TAT-QA | [Official repository](https://github.com/NExTplusplus/TAT-QA#license). The data is CC BY 4.0. | Install train, development, or the publisher's test gold release. Browse original tables, paragraphs, scales, and derivations. |
| ConvFinQA | [Official repository](https://github.com/czyssrs/ConvFinQA) with MIT license file and [paper](https://arxiv.org/abs/2210.03849). | Install one split from the publisher archive. Questions retain conversation IDs, turn order, and available reference answers. Test labels are withheld. |
| DocFinQA | [Publisher card](https://huggingface.co/datasets/kensho/DocFinQA) and [paper](https://arxiv.org/abs/2401.06991). Review the current card for usage terms. | Discover or import one long-document split. The local download or import ceiling is 512 MiB per split. Parquet loading uses batches. |
| MultiHiertt | [Official repository](https://github.com/psunlpgroup/MultiHiertt) with MIT license file and [paper](https://aclanthology.org/2022.acl-long.454/). | Import a JSON split from the [authors' Drive folder](https://drive.google.com/drive/folders/1ituEWZ5F7G9T9AZ0kzZZLrHNhRigHCZJ). Tables retain hierarchy and cell descriptions. Test labels are withheld. |

The app records the source revision, download size, and SHA-256 for each installed artifact. GitHub downloads match pinned release blob hashes. Hub downloads check published digests where available. Temporary source files are removed after validation. Staging and normalized storage require space beyond the advertised download size. FinanceBench PDF previews and evaluation downloads are also bounded. Downloads follow approved HTTPS hosts with TLS verification enabled.

## Controlled evaluations

Start from an installed split. Runs select the first eligible questions in release order, or file order for local imports. Use **Evaluation runs** to review metrics and their denominators, per-question output, errors, and source attribution. Cancellation takes effect between questions. JSON and CSV exports include results from partial and terminal runs. Groq runs are limited to 15 questions and 30 HTTP calls, including model discovery and retries. Retrieval runs can evaluate up to 100 questions without an API key.

| Task | Permitted input and metrics |
| --- | --- |
| Retrieval | FinQA and MultiHiertt rank independent publisher report passages or table cells. FinanceBench ranks the pages of the question's designated filing. Recall@K, MRR@K, and nDCG@K use released relevance IDs where those IDs map to the permitted corpus. |
| Numerical reasoning | Supported splits rank publisher context and ask Groq for a prediction and optional bounded operation list. A Decimal interpreter runs the model's proposed steps. FinQA-family comparisons use five decimal places for numeric execution values. MultiHiertt reports local answer EM and token F1. ConvFinQA supplies earlier questions from the same conversation as context. |
| Table-and-text QA | TAT-QA evaluates reference spans, scales, and numeric and counting answers using scale-aware TAT-QA-style EM and token F1. |
| PDF QA | FinanceBench ingests the question's designated official PDF transiently and retrieves pages before generation. It reports normalized exact match, numeric match where reference values are parseable, and annotated page attribution where available. Free-text matches are lexical, and the original FinanceBench study used human evaluation. |

These are local smoke and diagnostic protocols. The run label records the unit of retrieval and source context. The metrics apply to the selected subset and configuration. Text-only results and PDF results represent different tasks. TAT-QA and MultiHiertt local metrics approximate the published scoring conventions and may differ at normalization edges.

The benchmark runner reuses FinSight's BM25, RRF, embedding and reranking models, Groq transport, and numeric parsing. Hybrid mode requires working model downloads or caches. Questions and retrieved excerpts are the only data sent to Groq. Reference answers, annotated passages, reference programs, and prior reference answers remain outside the model input. Ranking starts from the allowed report or record context and avoids using reference labels to pick candidates. Failures, unscored cases, and missing evidence are visible.

## API

All routes use the `/api/v1` prefix.

| Purpose | Routes |
| --- | --- |
| Dataset catalog | `GET /benchmarks`, `GET /benchmarks/{id}`, `GET /benchmarks/{id}/status`, `GET /benchmarks/{id}/splits` |
| Manage data | `POST /benchmarks/{id}/install`, `POST /benchmarks/{id}/import`, `DELETE /benchmarks/{id}/installation` |
| Browse | `GET /benchmarks/{id}/samples`, `GET /benchmarks/{id}/samples/{question_id}`, `GET /benchmarks/{id}/filings/{filing}` |
| Evaluate | `POST /evaluations/run`, `GET /evaluations`, `GET /evaluations/{run_id}`, `POST /evaluations/{run_id}/cancel` |
| Review and export | `GET /evaluations/{run_id}/results`, `GET /evaluations/{run_id}/export?format=json\|csv` |
