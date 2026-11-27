# Model Evaluation

No fine-tuned LayoutLMv3 checkpoint or labelled invoice dataset is included. Therefore, no pretrained accuracy claim or fabricated score is made.

Evaluate extraction by comparing approved fields against a manually reviewed test set. Report exact match, field-level recall and precision. Compare OCR-only, OCR+Mistral and OCR+Mistral+LayoutLMv3 when a valid checkpoint is available.

## Recommended local inference settings

The default local configuration uses 2048 context tokens, 350 maximum generated
tokens, up to eight CPU threads, and a ten-minute Ollama model retention period.
The OCR text sent to Mistral is limited to 6000 characters. These defaults reduce
prompt and generation work while preserving the end and beginning of longer OCR
documents. All values can be overridden with `OLLAMA_NUM_CTX`,
`OLLAMA_NUM_PREDICT`, `OLLAMA_NUM_THREAD`, `OLLAMA_KEEP_ALIVE`, and
`OCR_TEXT_LIMIT`.

Benchmark each setting on the same five or more representative invoice images.
Record OCR seconds, Ollama prompt evaluation, Ollama generation, end-to-end
seconds, tokens per second, field-level accuracy, and GPU/CPU usage. Do not
claim GPU acceleration until `/api/ps` or hardware monitoring confirms it.
