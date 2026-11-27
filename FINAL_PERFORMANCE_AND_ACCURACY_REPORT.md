# FinSightAI Performance and Accuracy Report

## Summary

Invoice uploads now follow an OCR-first path: file validation, OpenCV
preprocessing, Tesseract OCR, deterministic field and line-item extraction,
financial validation, and SQLite persistence. Ordinary uploads and supported
financial questions do not require Ollama. Optional model suggestions run
separately after the invoice is saved.

The measured upload flow completed in 4.5551 seconds on one local, single-page
JPEG sample. That same manually reviewed sample exposed significant OCR
uncertainty, so it was retained in the database with processing status
`Needs Attention` and validation status `Validation Failed`. This is a safe
outcome, not a successful accuracy result.

## Changed files

| File | Change |
|---|---|
| `.env.example` | Documents environment-based database, storage, upload, OCR, Ollama, and CORS settings. |
| `.github/workflows/deploy.yml` | Removes the fixed API URL from the Pages build so the deployed UI can use its explicit connection flow. |
| `ARCHITECTURE.md` | Describes deterministic extraction, evidence, validation, optional enrichment, SQL-backed chat, and deployment limits. |
| `DEPLOYMENT.md` | Documents the local deployment and prerequisites/limitations for any future cloud deployment. |
| `INSTALLATION.md` | Makes Ollama optional and documents local persistent Docker volumes and setup. |
| `MODEL_EVALUATION.md` | Defines a labelled evaluation protocol and explains why current data cannot support an overall accuracy score. |
| `README.md` | Updates features, setup, model optionality, and the hosted-frontend connection model. |
| `USER_GUIDE.md` | Explains evidence, validation status, supported follow-ups, and exclusion of unverified records from verified spend. |
| `backend/database/database.py` | Adds additive schema migrations, OCR/evidence/confidence/enrichment fields, query indexes, performance metrics, and persistence helpers. New extracted rows leave `corrected_data` unset until a user correction. |
| `backend/llm/mistral_service.py` | Adds optional, suggestion-only invoice enrichment and records model timings; suggestions do not overwrite saved invoice data. |
| `backend/main.py` | Adds bounded upload handling, environment-configured storage/CORS, a separate single-worker enrichment executor, persistence of enrichment results/timings, and safe conversation-context handling. |
| `backend/models/invoice.py` | Allows currency to remain missing instead of silently assigning INR. |
| `backend/ocr/ocr_service.py` | Retains Tesseract word coordinates, retries low-confidence pages with adaptive thresholding when invoice-layout scoring improves, and reports cache-aware stage timings. |
| `backend/preprocessing/image_processor.py` | Adds adaptive threshold preprocessing as a selective fallback while preserving the existing default preprocessing path. |
| `backend/services/chat_assistant.py` | Implements deterministic intents, parameterized SQLite queries, supporting invoice rows, query timings, and database-ID-based invoice follow-ups. |
| `backend/services/invoice_extractor.py` | Adds deterministic header and coordinate-aware table extraction, evidence, confidence, Indian invoice labels, and conservative handling of missing fields. |
| `backend/services/invoice_pipeline.py` | Removes synchronous LLM extraction from uploads; performs extraction/validation/save and records processing-stage metrics before queuing optional enrichment. |
| `backend/validation/validation_engine.py` | Reconciles line-item amounts, subtotal, tax components, total tax, and grand total without inventing missing values. |
| `config.py` | Centralizes environment-based database/storage paths, upload limits, OCR limits, app environment, and configurable Ollama settings. |
| `docker-compose.yml` | Aligns the optional model default with Qwen and retains persistent local volume mounts and loopback-bound ports. |
| `frontend/.env.example` | Documents the configurable frontend API URL for local development. |
| `frontend/Dockerfile` | Keeps the frontend API URL as a build-time setting rather than embedding a fixed backend address. |
| `frontend/src/App.tsx` | Displays processing timings, evidence/confidence, enrichment status, and invoices/line items supporting assistant answers. |
| `frontend/src/services/api.ts` | Supports an explicitly configured API URL, permits HTTP only for loopback, and requires HTTPS for remote backends. |
| `tests/test_api.py` | Covers the revised API behavior, including correction from extracted data when no human correction exists. |
| `tests/test_chat_assistant.py` | Covers SQL-backed answers, supporting rows, follow-ups, missing invoice numbers, periods, GST, and search cases. |
| `tests/test_database.py` | Covers additive migration preservation, evidence/metrics/indexes, and initially unset correction data. |
| `tests/test_invoice_extractor.py` | Covers field evidence, missing values, OCR tax-rate handling, receipt labels, wrapped descriptions, and page-specific tables. |
| `tests/test_invoice_pipeline.py` | Covers the OCR-first save path, validation, and persisted performance/evidence behavior. |
| `tests/test_ocr.py` | Covers adaptive fallback selection, OCR cache timing, coordinate output, and existing document safeguards. |
| `tests/test_validation.py` | Covers line-item/subtotal reconciliation, tax-inclusive cases, and missing/uncertain financial data. |
| `FINAL_PERFORMANCE_AND_ACCURACY_REPORT.md` | Records measured results, tests, accuracy limitations, and remaining deployment constraints. |

## Measured processing performance

Measurements below are from an isolated FastAPI `TestClient` run that uploaded
one existing single-page JPEG, waited for processing, queried the saved
invoice, and ran an invoice follow-up. Database and upload storage were placed
in a temporary directory. Optional model inference was deliberately disabled
for this test.

### Cold upload

| Stage | Measured time |
|---|---:|
| Upload/write | 0.0301 s |
| File validation | 0.0003 s |
| Duplicate detection | 0.0320 s |
| PDF conversion | 0.0000 s (JPEG input) |
| OpenCV preprocessing, including adaptive fallback | 0.2145 s |
| Tesseract OCR | 3.2670 s |
| Deterministic extraction | 0.0260 s |
| Financial validation | 0.0003 s |
| Database save | 0.0234 s |
| Pipeline processing total | 4.5250 s |
| Upload-to-complete total | 4.5551 s |

Stage timings are independently measured and rounded; their sum need not equal
the end-to-end wall time exactly.

### Warm OCR-cache processing

The same stored source was processed in the same process against a separate
temporary database. This measures the in-memory OCR-cache path, **not** a
second cold boot or a general hardware warm-up benchmark.

| Stage | Measured time |
|---|---:|
| OCR cache lookup | 0.0010 s |
| Preprocessing | 0.0000 s |
| Tesseract OCR | 0.0000 s (cached result) |
| Deterministic extraction | 0.0087 s |
| Financial validation | 0.0001 s |
| Database save | 0.0261 s |
| Cached processing total | 0.1676 s |

The larger duplicate-detection portion of the warm run was 0.1294 seconds.
The warm total excludes the original upload and should not be compared with a
new-process cold run as if it were a hardware benchmark.

### Chat timing and correctness

For the uploaded invoice detail question, measured intent detection was
0.004488 s, SQL execution 0.057540 s, and response generation 0.000093 s.
For “What are its line items?”, follow-up intent detection was 0.000349 s,
SQL execution 0.046193 s, and response generation 0.000070 s.

Both responses referenced the saved invoice row; the follow-up returned its
stored line items even though OCR did not provide a usable invoice number.
The verified-expenditure query returned “No verified invoices are recorded
for any period” and no supporting rows, because this upload was not verified.
The chat numbers came from SQLite; no model generated financial amounts.

Optional Qwen enrichment timing is not reported: the local model was confirmed
installed, but inference was not started during this benchmark. The enrichment
path records its own inference and persistence timings when used.

## Extraction review and accuracy limitations

One manually reviewed receipt image was used as a diagnostic sample, not as a
representative test set. Exact match was observed for 3 of 8 manually checked
header/financial fields and 1 of 2 line-item amounts. Several header values
were missing or misread, and one item amount was truncated. The printed
financial values also appeared internally inconsistent. Validation therefore
did not mark the invoice verified; its processing status remained
`Needs Attention`.

These observations are not an overall accuracy score. The repository has no
independently labelled invoice set, and legacy `corrected_data` values were
automatically populated by older save behavior rather than verified by a
person. A statistically meaningful precision/recall or field-accuracy claim
requires a separate manually reviewed dataset.

## Database and chatbot verification

- The processing path stored OCR text/words, source file reference, extracted
  values, field evidence/confidence, validation status, and stage metrics.
- The temporary end-to-end database row was read back and matched the API
  result. New extracted invoices leave `corrected_data` null until correction.
- Financial totals and comparisons use parameterized SQL and only include
  `Verified` invoices. Invoice searches and detail lookups can still show
  unverified records with their status.
- Invoice detail and follow-up queries returned supporting invoice IDs and
  the saved line items. Missing values were described as absent rather than
  supplied by the model.
- Migrations are additive. A read-only check of the actual local database
  found 3 invoices and 5 line items both before and after the work. Processing
  jobs increased from 13 to 14 during earlier test activity; that extra row
  was left untouched. All final test-suite runs and end-to-end runs used
  temporary databases.

## Validation results

- Backend: **62 passed**, 16 FastAPI deprecation warnings.
- Python compilation: `python -m compileall -q backend config.py` passed.
- Frontend production build: passed. Vite emitted a non-fatal warning that the
  minified JavaScript chunk exceeds 500 kB.
- Frontend lint: passed.
- `git diff --check`: passed.
- Ollama: `qwen2.5:1.5b` was present locally; no inference was run.

## Remaining limitations

- Single-sample timings and accuracy observations do not establish population
  performance or extraction accuracy. More manually reviewed, representative
  invoices are needed, including multi-page and varied GST layouts.
- Low-quality OCR can still misread invoice numbers, dates, GSTINs, grand
  totals, and table columns. Such records remain unverified; human correction
  is required before they affect verified-spend totals.
- Optional AI results are suggestions only. Enrichment was not benchmarked
  here, and suggestion quality must be measured against labelled data before
  relying on it.
- The current deployment is local and single-instance. Cloud use requires
  HTTPS termination, secret management, persistent mounted database/file
  storage, restricted CORS, upload limits, and additional identity/tenant
  authorization. SQLite and the shared pairing token are not a
  multi-instance, multi-user cloud architecture.
- The UI production build has a large JavaScript chunk warning; build output
  remains successful.
