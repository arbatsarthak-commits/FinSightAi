# Windows Installation

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Install Tesseract OCR 5.5 and Ollama. Pull the speed-oriented default:

```powershell
ollama pull qwen2.5:1.5b
ollama serve
.\start_all.ps1
```

For the optional Qwen 2.5 3B profile, run `ollama pull qwen2.5:3b` and set
`OLLAMA_MODEL=qwen2.5:3b` in the ignored root `.env`. Copy `.env.example` to
`.env` to configure the model and OCR limits. PowerShell environment variables
override `.env` values.

# Docker

Docker exposes Ollama through `host.docker.internal`. Run:

```powershell
docker compose up --build
```
