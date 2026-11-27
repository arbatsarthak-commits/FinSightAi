# Model Evaluation

No manually labelled invoice evaluation dataset or fine-tuned LayoutLMv3 checkpoint is included. Existing `corrected_data` values are populated by the application save path and are not human-verified ground truth. Therefore, an overall extraction-accuracy score cannot be calculated from the current database.

Evaluate extraction by comparing fields against a separately maintained, manually reviewed test set. Report exact match, field-level precision/recall, confidence calibration, and reconciliation outcomes separately for headers, GST, line items, and totals. Keep uncertain values and source OCR evidence available for audit. Compare deterministic OCR-only processing with optional model suggestions only when a labelled test set and identical hardware/settings are used. Do not treat model suggestions as verified values or ground truth.

## Recommended local inference settings

The default optional local configuration uses Qwen 2.5 1.5B, 2048 context
tokens, 350 maximum generated tokens, up to eight CPU threads, and a ten-minute
Ollama model retention period. OCR text sent for enrichment is limited to 6000
characters. These settings affect optional enrichment only; ordinary invoice
uploads and deterministic chat queries do not require Ollama. Values can be
overridden with `OLLAMA_MODEL`, `OLLAMA_NUM_CTX`,
`OLLAMA_NUM_PREDICT`, `OLLAMA_NUM_THREAD`, `OLLAMA_KEEP_ALIVE`, and
`OCR_TEXT_LIMIT`.

Benchmark each setting on the same five or more representative invoice images.
Record OCR seconds, Ollama prompt evaluation, Ollama generation, end-to-end
seconds, tokens per second, field-level accuracy, and GPU/CPU usage. Do not
claim GPU acceleration until `/api/ps` or hardware monitoring confirms it.
