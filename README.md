# FinSightAI

FinSightAI is a React dashboard backed by a FastAPI service. Invoice uploads are processed with OpenCV, Tesseract OCR, and deterministic Python extraction, then saved with evidence and validation details in SQLite. Ollama/Qwen is optional and is used only for separate enrichment when deterministic extraction needs help. GitHub Pages hosts only the static frontend.

## Features

- JPG, PNG, and PDF invoice uploads with file validation, OpenCV preprocessing, and Tesseract OCR
- Coordinate-aware invoice and line-item extraction, OCR evidence, field confidence, and GST/total reconciliation
- Optional Qwen 2.5 1.5B enrichment, configurable through `OLLAMA_MODEL`; no model is required for ordinary uploads or database-backed queries
- GST-aware financial validation and file/invoice-number duplicate detection
- SQLite invoice history, OCR traceability, field-level evidence, stage metrics, processing logs, CSV export, and verified-expense analytics
- Dashboard charts, restart-aware processing jobs, and a conversational assistant using fixed, parameterized SQLite queries
- Authenticated invoice corrections and deletion, OCR field evidence, and local hardware/model status
- Optional LayoutLMv3 checkpoint inference; the standard workflow does not require it

## Architecture

```text
Browser (local Vite or GitHub Pages)
  └─ explicit Connect backend + local pairing token
      └─ FastAPI on 127.0.0.1:8000
          ├─ invoice upload and processing status
          ├─ deterministic fields, line items, evidence, and financial validation
          ├─ SQLite invoices, OCR traceability, and stage metrics
          ├─ optional background Ollama enrichment
          └─ parameterized database-grounded financial assistant
```

The backend is not hosted by GitHub Pages and is not exposed to the public internet. The browser submits the pairing token only after the user enters it; it stays in memory and is not built into the frontend. The backend accepts only configured frontend origins and binds to loopback when started with the supplied script.

## Required software

- Windows PowerShell
- Python 3.11 or later (use a version compatible with the pinned packages)
- Node.js 24 and npm
- Tesseract OCR 5, installed locally
- Optional: Ollama with the configured model installed (default `qwen2.5:1.5b`)

## Local setup

From the repository root, create and populate the Python environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Install the frontend dependencies:

```powershell
Set-Location .\frontend
npm ci
Set-Location ..
```

If PowerShell blocks environment activation, either adjust the policy for the current process or run the virtual-environment Python by its full path as the startup script does.

### Ollama and Qwen

Ollama is optional. Ordinary invoice processing and supported financial questions work without it. To enable background enrichment for ambiguous fields or line items, install Ollama and the configured model:

```powershell
ollama pull qwen2.5:1.5b
```

Set `OLLAMA_MODEL` to another locally installed model when desired. Ollama normally starts its local service automatically; otherwise run `ollama serve`. The backend defaults to `http://127.0.0.1:11434` and `qwen2.5:1.5b`; it never downloads a model automatically. Enrichment suggestions are stored separately and do not overwrite saved invoice fields or validation status.

### Tesseract OCR

Install Tesseract OCR 5. The default executable path is `C:\Program Files\Tesseract-OCR\tesseract.exe`. If yours differs, set it in the backend terminal before starting FastAPI:

```powershell
$env:TESSERACT_CMD = 'C:\Program Files\Tesseract-OCR\tesseract.exe'
```

The backend checks this executable when OCR is requested and reports its version in System settings. It detects common Windows installation paths and PATH when `TESSERACT_CMD` is unset.

### Start the local backend and frontend

Copy the example environment file once, then edit local settings if desired:

```powershell
Copy-Item .env.example .env
notepad .env
```

`.env` is loaded by the backend and is ignored by Git. Environment variables already set in PowerShell take precedence. Open two PowerShell terminals at the repository root.

In the backend terminal, optionally set local service configuration and start FastAPI:

```powershell
$env:TESSERACT_CMD = 'C:\Program Files\Tesseract-OCR\tesseract.exe'
$env:OLLAMA_HOST = 'http://127.0.0.1:11434'
$env:OLLAMA_MODEL = 'qwen2.5:1.5b'
$env:OLLAMA_NUM_CTX = '2048'
$env:OLLAMA_NUM_PREDICT = '350'
$env:OLLAMA_NUM_THREAD = '8'
$env:OLLAMA_KEEP_ALIVE = '10m'
$env:OCR_TEXT_LIMIT = '6000'
$env:OCR_TIMEOUT_SECONDS = '25'
$env:MAX_IMAGE_PIXELS = '40000000'
$env:MAX_PDF_PAGES = '30'
$env:FRONTEND_ORIGINS = 'http://127.0.0.1:5173,http://localhost:5173,https://arbatsarthak-commits.github.io'
.\start_backend.ps1
```

The script generates and stores a random local pairing token in the ignored `.local-api-token` file if one does not already exist. Keep the token private; enter it only into the app's **Connect backend** prompt. The API listens on `127.0.0.1:8000`.

In the frontend terminal:

```powershell
Set-Location .\frontend
npm run dev -- --host 127.0.0.1
```

Open `http://127.0.0.1:5173/`, choose **Connect backend**, and enter the token shown by the backend terminal. The frontend uses hash-based routes, so direct navigation and refreshes work both locally and under the GitHub Pages subdirectory.

Check backend health with:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

## GitHub Pages deployment

The workflow at `.github/workflows/deploy.yml` deploys the frontend when code is pushed to `main`; it also supports **Run workflow** through `workflow_dispatch`. It installs with `npm ci`, builds `frontend/` with Vite base path `/FinSightAi/`, and publishes `frontend/dist` using the official GitHub Pages actions.

1. In the GitHub repository, open **Settings → Pages** and set the build/deployment source to **GitHub Actions**.
2. Push the reviewed changes to `main`, or run **Actions → Deploy React frontend → Run workflow**.
3. Check that the build and deploy jobs complete successfully.
4. Visit <https://arbatsarthak-commits.github.io/FinSightAi/>.

Pages serves only static frontend assets. It does not host FastAPI, Tesseract, Ollama, the pairing token, invoices, or SQLite. The Pages build has no fixed backend URL. To use it, start the backend on the Windows computer that should process invoices, choose **Connect backend**, enter that computer's loopback API URL and local pairing token. The loopback URL refers to the visitor's own computer, not a public backend or a Vite development server.

The backend already allows the Pages origin `https://arbatsarthak-commits.github.io` in local mode. Origins are host-only: do not append `/FinSightAi/`. Keep `LOCAL_API_TOKEN` on the backend. Never set it as a `VITE_*` value, GitHub Actions build variable, or frontend environment variable. The current backend is a single-instance SQLite/filesystem application with shared-token authentication, not a multi-tenant cloud service; see [DEPLOYMENT.md](DEPLOYMENT.md) before considering any remote deployment.

### Browser and local-network limitations

The site is HTTPS while the local API uses HTTP on loopback. Chrome's Local Network Access permission (rolling out from Chrome 142) gates public-site requests to loopback; the HTTPS site may prompt for permission to access the local network. Grant it to `https://arbatsarthak-commits.github.io` in browser site settings, then retry. Other browsers and managed-browser policies may behave differently, including blocking local HTTP requests. See [Chrome's Local Network Access overview](https://developer.chrome.com/blog/local-network-access/). Do not disable browser security or expose/port-forward the backend to the internet to work around a blocked request. If the browser does not permit the connection, use the local Vite frontend at `http://127.0.0.1:5173/` instead.

## Troubleshooting

- **Pages assets return 404:** confirm Pages uses **GitHub Actions**, the deploy workflow succeeded, and the URL includes `/FinSightAi/`. The workflow sets the Vite base path; do not use the obsolete repository path.
- **Refresh or a route fails:** routes use `HashRouter`; navigate using the links in the app and preserve the `/#/route` fragment.
- **Backend connection fails:** confirm the backend terminal is still running at `127.0.0.1:8000`, use the current pairing token, and check the browser's local-network permission. For the hosted app, the CORS origin must be exactly `https://arbatsarthak-commits.github.io`.
- **Unauthorized response:** reconnect and enter the token printed by the currently running backend. Do not put that token in a URL, source file, frontend `.env`, or GitHub configuration.
- **OCR unavailable:** install Tesseract and set `TESSERACT_CMD` to its executable path before starting the backend.
- **Optional enrichment unavailable:** ordinary OCR uploads and supported database queries still work. Start Ollama, install the configured model if needed, and confirm `OLLAMA_HOST` and `OLLAMA_MODEL` in `.env` or the backend terminal.
- **Port is already in use:** stop the other local service or configure a coordinated port change in the backend, frontend API URL, and CORS settings.

## Local checks

```powershell
Set-Location .\frontend
npm ci
npm run build
npm run lint
Set-Location ..
.\.venv\Scripts\python.exe -m pytest
```

Build specifically for the Pages subdirectory and inspect the generated entry points:

```powershell
Set-Location .\frontend
$env:VITE_BASE_PATH = '/FinSightAi/'
$env:VITE_API_BASE_URL = 'http://127.0.0.1:8000'
npm run build
Get-Content .\dist\index.html
```

## Data and further documentation

Environment files, the pairing-token file, SQLite databases, invoice uploads, logs, and generated OCR output are excluded by `.gitignore`. Confirm `git status` before staging files; never add local invoices, databases, tokens, or real `.env` files.

See [DEPLOYMENT.md](DEPLOYMENT.md), [INSTALLATION.md](INSTALLATION.md), [ARCHITECTURE.md](ARCHITECTURE.md), [USER_GUIDE.md](USER_GUIDE.md), and [MODEL_EVALUATION.md](MODEL_EVALUATION.md) for additional project details.
