# Windows Installation

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Install Tesseract OCR 5.5 and Ollama. Pull Mistral:

```powershell
ollama pull mistral
ollama serve
.\start_all.ps1
```

Tesseract and Ollama settings can be overridden with environment variables from `.env.example`.

# Docker

Docker exposes Ollama through `host.docker.internal`. Run:

```powershell
docker compose up --build
```
