# FinSightAI Backend Data Sync and Accuracy Report

## Scope and original findings

This report covers the backend-only invoice diagnosis and repair. No frontend files, invoice-processing services outside the targeted extraction and validation path, AI model configuration, or real invoice records were changed.

The read-only diagnosis is documented in [BACKEND_DIAGNOSTIC_REPORT.md](./BACKEND_DIAGNOSTIC_REPORT.md), which was created before implementation changes. It found four existing invoice records and 14 line items, with no records marked `Verified`. The empty verified-only totals were therefore caused by validation state, not stale dashboard aggregates. It also found that:

- Missing monetary values were converted to zero during validation, allowing absent tax to affect reconciliation.
- Generic “Total” labels could be selected before more specific payable/amount labels.
- Layout-based vendor fallback confidence could not meet the pipeline's shared confidence threshold.
- Item amounts did not carry enough information to tell whether they represented taxable or gross values.
- The assistant excluded unverified records from financial calculations without separately explaining their known totals.
- Existing API responses did not set explicit no-cache headers.

## Implemented changes

### Extraction and validation

- [backend/models/invoice.py](./backend/models/invoice.py) now represents order and pack numbers, round-off, tax-inclusion basis, discount percentage, and line-item amount basis. Date parsing accepts additional Indian invoice date formats.
- [backend/services/invoice_extractor.py](./backend/services/invoice_extractor.py) prioritizes specific total labels over generic labels; recognizes receipt/order/pack identifiers, additional subtotal and round-off labels, and discount columns; preserves line-item amount-basis metadata; and records OCR confidence, extraction method, and pattern reliability with field evidence.
- [backend/services/invoice_pipeline.py](./backend/services/invoice_pipeline.py) applies different confidence thresholds to required fields and records structured reasons and evidence when a value falls below its threshold. Such records remain `Needs Attention`; parsing alone does not verify them.
- [backend/validation/validation_engine.py](./backend/validation/validation_engine.py) uses `None` for missing or invalid monetary data, preserves fractional quantities, and distinguishes known taxable/gross/unknown line-item amounts. It reconciles explicit discounts, GST components, subtotal, grand total, and recorded round-off without filling absent values with zero. Ambiguous or incomplete data receives warnings; confirmed mismatches fail validation.

### Database analytics and assistant

- [backend/database/database.py](./backend/database/database.py) retains the existing verified-only response keys and adds separate provisional summaries for totals, tax, vendors, categories, and monthly spend. Counts distinguish records with known amounts from those with missing amounts.
- [backend/services/chat_assistant.py](./backend/services/chat_assistant.py) keeps financial calculations SQL-grounded and separates verified from provisional results for total, monthly/yearly, average, tax/GST, vendor, category, and comparison queries. Supporting provisional invoices are returned separately with their validation status. Missing totals or tax are reported as unrecorded rather than presented as zero.
- [backend/main.py](./backend/main.py) sets `Cache-Control: no-store` and related headers on API responses so financial data is fetched fresh.

### Regression coverage

- [tests/test_validation.py](./tests/test_validation.py): missing/partial GST, fractional quantities, and recorded/unrecorded round-off.
- [tests/test_invoice_extractor.py](./tests/test_invoice_extractor.py): explicit total-label precedence, order/pack identifiers, OCR evidence, and line-item extraction.
- [tests/test_invoice_pipeline.py](./tests/test_invoice_pipeline.py): confidence-threshold reasons and evidence persistence.
- [tests/test_database.py](./tests/test_database.py): separate verified/provisional dashboard aggregates.
- [tests/test_chat_assistant.py](./tests/test_chat_assistant.py): SQL-grounded provisional totals, monthly/category/vendor summaries, and missing tax/amount behavior.
- [tests/test_api.py](./tests/test_api.py): API no-cache response headers.

## Data safety and remaining limitations

No schema migration was run, no backup or rewrite of the live database was performed, and no existing invoice was automatically changed or marked verified. A final read-only check confirmed the live database still contains four invoice rows and 14 line-item rows; its validation-state counts remain one `Needs Review` and three `Validation Failed`.

The existing records with missing OCR/evidence, unavailable source files, or replay mismatches remain unresolved for manual review. This implementation deliberately does not infer replacements for absent values or automatically upgrade those records to `Verified`. A user with source documents should correct or reprocess them and review the resulting evidence.

No warm/cold OCR benchmark or extraction-accuracy percentage is reported: the existing invoices are not a labeled accuracy dataset, and no production processing benchmark was run as part of this backend repair. The measured test-suite runtime below is not an invoice-processing benchmark.

## Verification results

- Full backend test suite: **72 passed**, **16 FastAPI deprecation warnings**, in **17.18 seconds**.
- Backend `compileall`: passed.
- Pylance syntax check for the changed assistant module: no syntax errors.
- `git diff --check`: passed.
- The live database check used a read-only SQLite connection.
