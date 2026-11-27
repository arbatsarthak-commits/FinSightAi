# User Guide

1. Connect the UI to the backend with the local pairing token.
2. Upload an invoice in `Upload invoice` and select `Process Invoice Automatically`.
3. Follow the live processing stages. Validated invoices are saved automatically.
4. Check extracted fields, validation warnings and measured stage timings in the result.
5. Incomplete or inconsistent invoices are retained in history as `Needs Attention` and excluded from financial totals.
6. Use `Invoice history` to search, filter, inspect, correct header fields, export, or delete invoices. Deletion also removes the stored upload only when no other record references it.
7. Use `Analytics` for verified expense and tax summaries.
8. Ask follow-up financial questions in `AI expense assistant`. The assistant uses fixed parameterized queries against verified records; the model never writes or executes SQL.
9. Processing jobs survive a backend restart as saved status records. A job interrupted by a restart is marked failed with instructions to submit the stored upload again.
