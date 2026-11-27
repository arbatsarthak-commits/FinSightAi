# FinSightAI deployment

## Deployment model

GitHub Pages serves the React/Vite frontend at
<https://arbatsarthak-commits.github.io/FinSightAi/>. FastAPI, Ollama/Qwen,
Tesseract/OpenCV, invoice uploads, and SQLite remain on the user's Windows
computer. The static website is not a backend host and does not receive local
database files or invoice documents as part of deployment.

The frontend deliberately calls `http://127.0.0.1:8000`, which means the
computer running the browser. The user must start the backend on that same
computer and enter its locally generated pairing token in **Connect backend**.
The token remains in frontend memory and is sent in the `X-Pairing-Token`
header. Never provide it as a `VITE_*` setting or build secret.

## GitHub Pages setup

1. In GitHub repository **Settings → Pages**, choose **GitHub Actions** as the
   deployment source.
2. Push to `main` or start **Actions → Deploy React frontend → Run workflow**.
3. Confirm both workflow jobs succeed, then open the Pages URL above.

The single workflow at `.github/workflows/deploy.yml` runs `npm ci` in
`frontend/`, builds with `/FinSightAi/` as Vite's base path, uploads
`frontend/dist`, and deploys with the official Pages actions. It runs on pushes
to `main` and supports `workflow_dispatch`. Required workflow permissions are
`contents: read`, `pages: write`, and `id-token: write`.

The backend permits `https://arbatsarthak-commits.github.io` as a CORS origin.
The origin is host-only and must not include `/FinSightAi/`. The backend binds
to `127.0.0.1`; do not bind it publicly or configure a router port-forward.

## Run and connect the local backend

Install the prerequisites and Python dependencies as described in
[README.md](README.md). Start Ollama and ensure `qwen2.5:1.5b` is available. In a
PowerShell terminal at the repository root, set any local overrides and start
FastAPI:

```powershell
$env:TESSERACT_CMD = 'C:\Program Files\Tesseract-OCR\tesseract.exe'
$env:OLLAMA_HOST = 'http://localhost:11434'
$env:OLLAMA_MODEL = 'qwen2.5:1.5b'
$env:FRONTEND_ORIGINS = 'http://127.0.0.1:5173,http://localhost:5173,https://arbatsarthak-commits.github.io'
.\start_backend.ps1
```

`start_backend.ps1` creates a random token in the ignored `.local-api-token`
file if `LOCAL_API_TOKEN` is not already set, then prints it to the backend
terminal. Enter it only in the app's **Connect backend** prompt. Verify the
health endpoint with:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

For local development, run the frontend in a second terminal:

```powershell
Set-Location .\frontend
npm ci
npm run dev -- --host 127.0.0.1
```

Open `http://127.0.0.1:5173/`. Hash-based routing keeps app routes refreshable
on both Vite and GitHub Pages.

## Browser connection limitations

An HTTPS page requesting a local HTTP service can encounter browser
Local Network Access protections. Chrome's permission prompt is rolling out
from Chrome 142 and requires user approval for a public website to access
loopback. Depending on browser/version or managed-browser policy, the user may
need to grant local-network access to
`https://arbatsarthak-commits.github.io` in site settings, and another browser
may block the request. The backend handles CORS preflight for the pairing
header and remains loopback-only. See
[Chrome's Local Network Access overview](https://developer.chrome.com/blog/local-network-access/).
If the browser blocks loopback requests despite permission, use the local Vite
frontend; do not disable browser protections or expose the backend publicly.
This user-controlled, loopback-only design avoids introducing a public relay or
remote backend.

## Checks and troubleshooting

```powershell
Set-Location .\frontend
npm ci
$env:VITE_BASE_PATH = '/FinSightAi/'
$env:VITE_API_BASE_URL = 'http://127.0.0.1:8000'
npm run build
Get-Content .\dist\index.html
```

Confirm the output references `/FinSightAi/` assets and that the favicon path
is also under the repository prefix. GitHub Actions performs the same build.

- Pages asset 404: verify **GitHub Actions** is selected in Pages settings and
  the workflow completed; the site path is case-sensitive and includes
  `/FinSightAi/`.
- Failed connection: start the local backend, check `/api/health`, reconnect
  with the current token, and grant browser local-network permission if shown.
- 401 response: use the token printed by that running backend; never move it
  into a frontend config or GitHub Actions variable.
- OCR/model unavailable: verify `TESSERACT_CMD`, that Ollama is running, and
  that `ollama pull qwen2.5:1.5b` has completed.

The backend reads `.env` from the repository root; process environment values
take precedence. `.gitignore` excludes environment files, the token file,
SQLite databases, uploads, logs, and generated OCR output.
