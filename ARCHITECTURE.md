# System Architecture

The application follows this pipeline:

1. JPG, JPEG, PNG or PDF upload.
2. File validation and SHA-256 duplicate detection before OCR or model inference.
3. PDF page conversion when needed, followed by conditional OpenCV contrast enhancement, deskewing and thresholding.
4. Tesseract OCR records page text and word-level confidence/bounding boxes. Low-confidence pages may be retried with adaptive thresholding when its invoice-layout score is better.
5. Deterministic Python extraction uses labels, OCR word coordinates, grouped rows, and conservative field evidence. Uncertain values remain missing or are marked for attention.
6. Financial validation reconciles line amounts, subtotal, GST components, total tax, and grand total. SQLite stores the invoice, OCR traceability, evidence, status, and stage metrics without requiring model inference.
7. A single-worker background task may request optional Ollama/Qwen suggestions for ambiguous fields, vendor names, line items, or categories. Suggestions never overwrite saved values or status.
8. React/Recharts analytics and the assistant use parameterized SQL for financial answers. Supported intents are deterministic and common queries do not wait for Ollama; the model may interpret only unsupported phrasings and never generates executable SQL.

The processing API reports stage progress, a queue position, and measured timings. Job states are persisted and interrupted jobs are marked recoverable after a backend restart. File hashes are checked before OCR work, while optional inference uses a separate single-worker executor and shared lock.

Legacy approval columns remain in SQLite to preserve existing data. Authenticated correction and deletion routes are available; invoice analytics continue to include only verified records.

SQLite, filesystem storage, API URL, OCR executable, upload limit, CORS origins, and Ollama endpoint/model are configured through environment variables. The shipped deployment is local and single-instance; see [DEPLOYMENT.md](DEPLOYMENT.md) for cloud prerequisites and current authentication/storage limitations.

LayoutLMv3 is an optional neural-document module. It is not downloaded by startup and is intended for labelled data and a fine-tuned checkpoint.
