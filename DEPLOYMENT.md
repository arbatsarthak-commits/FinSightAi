# Deployment

## Local Windows

Run:

```powershell
ollama serve
.\start_all.ps1
```

The React app runs on Vite at `http://127.0.0.1:5173`; FastAPI runs at `http://127.0.0.1:8000`.

## GitHub Pages

The `.github/workflows/deploy.yml` workflow runs on pushes to `main` and can also be started manually. It runs `npm ci`, builds `frontend/` with `VITE_BASE_PATH=/LLM-based-Expense-tracker-/`, and publishes `frontend/dist` using GitHub Pages.

GitHub Pages hosts static files only. It cannot run OCR, Ollama or SQLite. A deployed public frontend requires the user to start FastAPI locally and initiate a user-controlled backend connection.

## Local pairing

The backend startup script creates a random pairing token and prints it in the backend console. Click **Connect backend** in the website and enter that token. The frontend keeps the token in memory only; it is not embedded in the compiled JavaScript. Requests require `X-Pairing-Token`. CORS uses explicit origins, and local startup binds only to `127.0.0.1`.

For GitHub Pages, include the published origin in `FRONTEND_ORIGINS` before starting the backend. The example configuration includes `https://arbatsarthak-commits.github.io`; origins contain no repository path. The static frontend continues to use `http://127.0.0.1:8000` as its default API URL. Pages does not host FastAPI, Ollama, OCR, or SQLite.

For a Windows PowerShell launch, set the origin explicitly in the backend terminal before starting it:

```powershell
$env:FRONTEND_ORIGINS = "http://127.0.0.1:5173,http://localhost:5173,https://arbatsarthak-commits.github.io"
.\start_backend.ps1
```

The hosted site connects to the user's own local backend only after they select **Connect backend** and enter the pairing token. Keep `LOCAL_API_TOKEN` on the backend; it is not a Vite setting and must not be added to GitHub Actions secrets, build variables, frontend `.env` files, or generated artifacts. Requests retain the `X-Pairing-Token` header.

Because GitHub Pages is HTTPS and the API is local HTTP, a supported browser may prompt to allow the site to access devices on the local network. Grant that permission to `https://arbatsarthak-commits.github.io` in the browser's site settings (Chrome/Edge: Site settings → Local network access, when available), then retry **Connect backend**. Also allow the backend in Windows Firewall for loopback use. Browser versions may use different permission labels or require a browser restart. If the browser does not allow this connection, use the local Vite frontend instead; do not expose the backend to the public internet as a workaround.

## Private document files and Git history

Invoice samples and screenshots containing invoice or personal financial information are excluded by `.gitignore` and removed from the current Git index without deleting their local copies. This does not remove versions from earlier commits or an already-pushed remote. If those commits were pushed, coordinate a repository-wide history rewrite using a reviewed `git filter-repo` path list, then force-push the rewritten branches/tags and ask collaborators to re-clone. Check forks, pull-request refs, caches, and backups; GitHub may retain data after a rewrite. Do not rewrite shared history without coordinating with collaborators.

For Docker, generate a random token in PowerShell before starting Compose:

```powershell
$env:LOCAL_API_TOKEN = (& python -c "import secrets; print(secrets.token_urlsafe(32))").Trim()
docker compose up --build
```

Paste the printed environment token into the app's **Connect backend** prompt. Ports are mapped to loopback only. Do not commit the token.
