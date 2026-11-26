# AI-Powered Invoice Intelligence and Expense Analytics

An original React/FastAPI invoice processing application for image/PDF OCR, Mistral-based structured extraction, automatic financial validation and SQLite-backed expense analytics.

## Main Features

- Conditional OpenCV contrast enhancement, deskewing and Otsu thresholding
- Tesseract OCR with page text, word boxes and confidence
- JPG, JPEG, PNG and PDF support
- Pydantic invoice schema with one batched Mistral/Ollama extraction and categorization request
- GST-aware subtotal, tax and grand-total validation
- Same-file and invoice-number duplicate detection before insertion
- Automatic saving of validated invoices; incomplete or inconsistent records are marked Needs Attention
- Per-stage progress and measured processing timings
- Normalized SQLite tables and processing logs
- React dashboard and Recharts analytics
- Restricted read-only natural-language SQL assistant
- Optional LayoutLMv3 checkpoint inference and training scaffold

## Run Locally

```powershell
ollama pull mistral
ollama serve
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
.\start_all.ps1
```

Open http://127.0.0.1:5173. The backend runs at http://127.0.0.1:8000. Configure Tesseract and Ollama using `.env.example`.

The backend startup script creates a local pairing token and prints it in its terminal. Use **Connect backend** in the UI and enter that token. The frontend keeps the token in memory and does not bundle it.

## Architecture

Upload → file/hash validation → PDF conversion → OpenCV preprocessing → Tesseract OCR → Mistral extraction and categorization → Pydantic and financial validation → SQLite → analytics.

See [ARCHITECTURE.md](ARCHITECTURE.md), [INSTALLATION.md](INSTALLATION.md), [USER_GUIDE.md](USER_GUIDE.md), and [MODEL_EVALUATION.md](MODEL_EVALUATION.md).

## LayoutLMv3 Status

LayoutLMv3 is optional and is never downloaded at startup. Set `LAYOUTLM_MODEL` to a local fine-tuned checkpoint or Hugging Face checkpoint. The standard OCR+Mistral workflow remains usable without it. No GST-specific pretrained accuracy is claimed.
