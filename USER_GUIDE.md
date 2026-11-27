# User Guide

1. Connect the UI to the backend with the local pairing token.
2. Upload an invoice in `Upload invoice` and select `Process Invoice Automatically`.
3. Follow the live upload, preprocessing, OCR, extraction, validation, and save stages. OCR-first extraction and saving do not wait for an LLM.
4. Check extracted fields, OCR evidence, confidence, validation warnings, optional enrichment status, and measured stage timings in the result.
5. Incomplete or inconsistent invoices are retained in history as `Needs Attention` and excluded from financial totals.
6. Use `Invoice history` to search, filter, inspect, correct header fields, export, or delete invoices. Deletion also removes the stored upload only when no other record references it.
7. Use `Analytics` for verified expense and tax summaries.
8. Ask financial questions in `AI expense assistant`. Financial totals come from parameterized SQLite queries and show supporting invoices; records not marked `Verified` are excluded from verified-spend totals.
9. Ask follow-up questions about the vendor or invoice from a prior answer. The assistant resolves the reference from conversation context and looks up the saved invoice rows again.
10. Processing jobs survive a backend restart as saved status records. A job interrupted by a restart is marked failed with instructions to submit the stored upload again.
