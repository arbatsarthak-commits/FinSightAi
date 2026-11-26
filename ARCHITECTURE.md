# System Architecture

The application follows this pipeline:

1. JPG, JPEG, PNG or PDF upload.
2. File validation and SHA-256 duplicate detection before OCR or model inference.
3. PDF page conversion when needed, followed by conditional OpenCV contrast enhancement, deskewing and thresholding.
4. One Tesseract OCR pass per page, including page text and word-level confidence/bounding boxes.
5. One Pydantic-validated Mistral extraction and item categorization request through Ollama.
6. Financial validation, then automatic SQLite storage with Needs Attention status for incomplete or inconsistent records.
7. React/Recharts analytics using only Verified invoices and a read-only FastAPI SQL assistant.

The processing API reports real stage progress and high-resolution timings. File hashes are checked before OCR/model work, and database uniqueness plus serialized local inference prevents duplicate records from concurrent requests.

Legacy approval and correction columns remain in SQLite to preserve existing data, but new processing, route behavior and analytics no longer depend on them.

LayoutLMv3 is an optional neural-document module. It is not downloaded by startup and is intended for labelled data and a fine-tuned checkpoint.
