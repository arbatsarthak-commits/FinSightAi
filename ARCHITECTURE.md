# System Architecture

The application follows this pipeline:

1. JPG, JPEG, PNG or PDF upload.
2. File validation and SHA-256 duplicate detection before OCR or model inference.
3. PDF page conversion when needed, followed by conditional OpenCV contrast enhancement, deskewing and thresholding.
4. One Tesseract OCR pass per page, including page text and word-level confidence/bounding boxes.
5. One Pydantic-validated Qwen extraction and item categorization request through Ollama, with at most one targeted repair call for malformed/schema-invalid output.
6. Financial validation, then automatic SQLite storage with Needs Attention status for incomplete or inconsistent records.
7. React/Recharts analytics using only Verified invoices and a conversational assistant that maps intents to fixed, parameterized SQLite queries; Ollama can classify unsupported phrasings but never generates executable SQL.

The processing API reports stage progress, a queue position, and high-resolution timings. Job states are persisted and interrupted jobs are marked recoverable after a backend restart. File hashes are checked before OCR/model work, and local inference remains serialized to prevent resource contention.

Legacy approval columns remain in SQLite to preserve existing data. Authenticated correction and deletion routes are available; invoice analytics continue to include only verified records.

LayoutLMv3 is an optional neural-document module. It is not downloaded by startup and is intended for labelled data and a fine-tuned checkpoint.
