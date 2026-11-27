# Windows Installation

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Install Tesseract OCR 5.5. Ollama is optional; uploads and supported database queries do not require a model. To enable background enrichment, install Ollama and the configured model:

```powershell
ollama pull qwen2.5:1.5b
```

Copy `.env.example` to `.env` to configure OCR limits, database/storage paths,
the optional model, upload size, CORS origins, and the local pairing token.
PowerShell environment variables override `.env` values. Set `OLLAMA_MODEL` to
another installed model if needed; the application does not download models.
Use `.\start_backend.ps1` and start the frontend separately as described in
[README.md](README.md).

# Docker

Docker Compose keeps the API and frontend ports bound to loopback and stores
the database and uploaded files in the persistent `invoice-data` volume. Set
a private `LOCAL_API_TOKEN` before starting. Ollama is optional; when enabled,
Compose reaches the host service through `host.docker.internal`. Run:

```powershell
docker compose up --build
```
