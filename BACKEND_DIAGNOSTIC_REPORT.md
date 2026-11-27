# FinSightAI Backend Data Diagnostic

**Audit date:** 2026-11-27  
**Audit mode:** Read-only SQLite inspection and in-memory OCR replay. No database rows, files, or application source were changed during this audit.

## Database identity and scope

- `config.DB_PATH` resolves to the project-root `ocr_master_table.db`.
- `INVOICE_DB_PATH` is not set in the active environment. The configured database exists and contains four invoice rows.
- A repository file scan found no other `.db`, `.sqlite`, or `.sqlite3` database.
- The database has 14 line-item rows, 17 processing-job records, and no duplicate `source_hash` groups.
- Invoice 1's referenced source file is unavailable. The source files for invoices 2–4 exist and match their stored source hashes.
- The audit used read-only SQLite connections. OCR replay for invoices 2–4 was performed in memory; no replay results were saved.

## Dashboard and assistant diagnosis

The four records have no `Verified` status. `get_dashboard_data()` correctly filters verified totals, monthly totals, vendors, and categories on `validation_status = 'Verified'`. It counts all four records but reports zero verified count, spend, and tax. Therefore the empty verified dashboard/chart totals are a consequence of validation states, not stale in-memory dashboard aggregates.

The assistant applies the same verified-only filter to expenditure and tax calculations. With no verified records, it correctly returns that no verified invoices exist, but it does not calculate or explain provisional amounts from records awaiting review. Its invoice and pending-record queries can already access unverified records.

## Per-record findings

| Invoice ID | Stored state | Read-only findings |
|---|---|---|
| 1 | Needs Review / Needs Attention | The four required fields (invoice number, date, vendor, and grand total) are absent. No OCR text, OCR words, field evidence, or confidence values are stored; its source file is unavailable. One line-item row exists but has no usable amount. The cause cannot be reconstructed from the stored record alone. |
| 2 | Validation Failed / Needs Attention | Required fields are populated, but OCR/evidence/confidence were not stored. Subtotal is absent and the GST component set is incomplete. Revalidating the persisted payload produces **Needs Attention with warnings only and no validation errors**, so the stored `Validation Failed` state does not match the current validator result. Its source file and hash are available. Re-running current OCR/extraction from that file does not reproduce the saved required fields: invoice number and grand total are not found, invoice-date confidence is 0.572, and the vendor is a layout fallback with confidence 0.65. The replay also reports item/subtotal mismatch and missing tax details. |
| 3 | Validation Failed / Needs Attention | Required fields are populated, but OCR/evidence/confidence were not stored. The persisted payload fails the current subtotal-to-item-sum and subtotal-plus-tax-to-grand-total checks; the GST component breakdown is absent. Its available, hash-matching source file does not reproduce the saved values under current OCR/extraction: vendor is not identified, invoice/date/grand-total confidence is low (0.565 / 0.387 / 0.410), and subtotal is not found. The replay is Needs Attention rather than Validation Failed, with subtotal and suspicious-total warnings. Historical OCR evidence is unavailable, so the discrepancy cannot be attributed conclusively to a specific earlier parser version or manual edit. |
| 4 | Validation Failed / Needs Attention | OCR text and word coordinates are stored. Invoice number, date, and vendor are present with OCR confidence 0.867, 0.915, and 0.868. Grand total and subtotal are absent; only one GST component is present and total tax is missing. Nine line items were detected, with eight quantity/rate-to-amount comparisons failing under the current validator. The OCR contains a specific “Total Amount” summary line, but extraction chooses an earlier generic “Total” occurrence and returns no grand total. The table header detects description, quantity, unit price, and amount columns, but the row amounts do not reconcile to quantity × unit price. |

The processing log records a generic successful save for each invoice but does not retain the validation messages. Processing-job results provide detailed validation results for invoices 3 and 4; there is no matching job result for invoices 1 and 2. Thus not all historical validation detail is recoverable.

## Confirmed implementation causes

1. **Verified-only aggregates explain the displayed zeros.** The current aggregate queries are fresh database reads, but no row currently qualifies as verified.
2. **The assistant cannot explain provisional financial data.** Its expenditure/tax calculations query only verified rows, so unverified extracted totals are omitted rather than separately reported.
3. **Vendor fallback cannot meet the pipeline's mandatory threshold.** The extractor caps layout-fallback vendor confidence at 0.65 while `_REQUIRED_CONFIDENCE` is 0.75. Such a value necessarily remains below threshold, regardless of high OCR readability.
4. **Missing money is treated as zero by validation.** `money(None)` returns `Decimal("0")`. Consequently, missing tax can be treated as zero when deciding whether to compare a line amount with quantity × unit price. The validator also assumes subtotal + tax is the same basis as grand total, without modeling round-off or tax-inclusive totals.
5. **Generic total-label selection is order-dependent.** Grand-total extraction accepts a bare “total” alias and returns the first matching line, rather than preferring a specific payable/total-amount label. This is the observed reason invoice 4's later “Total Amount” value is missed.
6. **Receipt summary aliases and table parsing are incomplete.** “Sum” / “Sum Amount” is not a subtotal alias. The current layout parser does not establish whether an `amount` column is tax-inclusive, taxable, discounted, or a final row total before comparing it financially.
7. **Historical evidence is inconsistent/incomplete.** Invoices 1–3 have no persisted OCR/evidence/confidence; invoice 1 has no source file. Reprocessing source files for invoices 2 and 3 does not reproduce the stored payload, so those records must not be automatically rewritten or marked verified.

## Persistence and synchronization observations

- Invoice rows and line items are inserted inside one `db_connection()` transaction in `save_extracted_invoice()`.
- `process_invoice()` saves the invoice before returning; the job is marked complete after that result returns.
- Dashboard functions query SQLite on each request; no in-memory aggregate cache was found.
- No `Cache-Control`/`no-cache` response handling was found on the invoice, analytics, or assistant data endpoints.
- Existing invoice, vendor, date, validation-status, category, and line-item indexes are present.
- This diagnostic did not run schema initialization against the real database and made no changes. A backup will be created outside tracked source files before any schema/data migration.

## Safe handling limitations

This report deliberately excludes vendor names, invoice numbers, GSTINs, customer data, OCR text, raw line-item descriptions, and monetary values. Invoice 1's extraction cause and the historical origin of the invoice 2–3 discrepancies cannot be determined from retained evidence. No invoice will be bulk-marked verified or overwritten as part of the repair.
