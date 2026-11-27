# Fixes Applied

## Reliability and processing

- Made the default Ollama model configurable and set it to Qwen 2.5 1.5B. The backend checks whether the selected model is installed and does not download models automatically.
- Added local `.env` loading, common Windows Tesseract path detection, OCR timeouts, image pixel limits, image validation, and PDF page limits with page-specific errors.
- Improved extraction with deterministic invoice-field rules, source evidence, targeted repair of malformed model output, and vendor-aware invoice-number duplicate checks.
- Persisted processing job state in SQLite and report jobs interrupted by a backend restart with retry guidance.
- Added actionable errors when configured OCR/model services are unavailable.

## Assistant and invoice workflows

- Added a conversational financial assistant that uses fixed, parameterized SQLite queries rather than model-generated SQL. Financial summaries use verified invoices and support bounded follow-up context.
- Added authenticated invoice correction and deletion, including financial revalidation and safe removal of unreferenced uploads.
- Enabled `PUT` and `DELETE` in the configured CORS methods so browser preflight requests for invoice corrections and deletion succeed.

## Interface and documentation

- Reworked the dashboard, invoice register, assistant, and settings views for responsive desktop and mobile layouts.
- Updated setup, deployment, architecture, and user documentation for the model configuration, local backend, job recovery, assistant, and invoice workflows.

## Validation and measured performance

- Python regression tests: **46 passed**.
- Python compilation: `python -m compileall -q backend config.py tests` passed.
- Frontend production build and lint passed. Vite reports a non-blocking large-bundle warning (792.17 kB minified JavaScript).
- Live CORS preflights for `PUT` and `DELETE` from the configured GitHub Pages origin both returned HTTP 200.
- OCR sample measurement on `19e44c289e935164.jpeg`: 1 page, 130 recognized words, 56.98 confidence; preprocessing 0.2822 s, OCR 2.5128 s, total 3.1166 s.
- Observed system: AMD Ryzen 5 7520U (4 cores/8 logical processors), approximately 15.3 GB RAM; Tesseract 5.5.3 and Ollama 0.40.18 installed.

## Limitations

- The configured `qwen2.5:1.5b` model was not installed during validation. No model was downloaded or run, so model extraction quality and cold/warm inference time—including any end-to-end 10-second target—remain unverified. A larger Mistral model was present, but not launched because available memory was limited.
