# FinSightAI Backend Connection Fix Report

## Root cause

The connection action in `frontend/src/App.tsx` used two sequential native `window.prompt()` calls. The first prompt asked for a generic backend URL, while `start_backend.ps1` told users to enter the pairing token in the generic connection prompt. Pasting the token into the URL prompt reached `new URL(token)` in the API service and caused an uncaught `Invalid URL` exception.

The backend authentication contract was already appropriate: `GET /api/health` is unauthenticated, while `GET /api/system/status` requires the `X-Pairing-Token` header. The GitHub Pages origin was already included in the local backend CORS allowlist, so backend authentication and CORS policy were left unchanged.

## Files changed

- `frontend/src/App.tsx` — Replaced the native prompt sequence with one React modal containing the URL and password-style token fields, token visibility toggle, connection status, loading state, and actionable errors. On success, the app closes the modal and invalidates queries.
- `frontend/src/services/api.ts` — Added safe URL validation and normalization, loopback-only HTTP validation, token-in-URL detection, timed unauthenticated health verification, and authenticated status verification using `X-Pairing-Token`. Tokens remain in memory and are cleared when a connection attempt begins or authentication fails. Network errors explain backend, port, CORS, and browser local-network possibilities without presenting raw JavaScript exceptions.
- `start_backend.ps1` — Preserved secure token generation and environment handling. It now prints the requested URL and field-specific token instructions after Uvicorn has completed startup.
- `CONNECTION_FIX_REPORT.md` — This report.

## Connection workflow

1. The user opens the single Connect Backend modal. The URL defaults to `http://127.0.0.1:8000`; the token field starts empty.
2. The frontend validates the URL before parsing it, rejects token-like URL input with the requested guidance, normalizes trailing slashes, allows HTTP only for loopback hosts, and requires HTTPS for remote hosts.
3. The frontend requires a non-empty pairing token and calls `/api/health` without authentication.
4. It then calls `/api/system/status` with the supplied `X-Pairing-Token` header.
5. Only an authenticated successful status response marks the app connected. On success, the modal closes and cached application queries refresh.

## Security and browser requirements

- The pairing token is not stored in local storage, environment variables, URL parameters, or logs. It is held in application memory and sent only in the existing authentication header.
- The backend token generation, authentication requirement, CORS allowlist, and loopback binding were not weakened or changed.
- A browser may block a hosted HTTPS page from reaching a local HTTP backend unless the user grants local-network access. Browser permission wording varies. Fetch cannot reliably distinguish a browser CORS/local-network denial from a stopped backend or refused port, so the UI gives these as troubleshooting causes instead of falsely reporting a bad token.
- Remote backend URLs must use HTTPS.

## Verification

- `npm run build` (from `frontend/`) — passed. Vite emitted an advisory that the minified JavaScript bundle is larger than 500 kB.
- `npm run lint` (from `frontend/`) — passed.
- `.venv\\Scripts\\python.exe -m pytest tests\\test_api.py -q` — 21 passed. This includes unauthenticated health, authenticated status, rejection of unauthenticated private routes, and GitHub Pages CORS preflight coverage. The suite emitted 16 FastAPI deprecation warnings.
- Browser smoke test against an isolated local backend — correct token connected and refreshed the dashboard; a wrong token displayed the distinct HTTP 401 message; token-in-URL, empty URL, and empty-token inputs displayed their respective validation messages; an unused port displayed a backend/port/network diagnostic rather than an incorrect-token message.
- `start_backend.ps1` — PowerShell parser reported valid syntax; the embedded Python code parsed successfully; and the installed Uvicorn `Server.startup` method signature accepts the override used by the script.

The browser smoke test used loopback port `8765` with a test-only token; it did not use the user's generated token or alter the project's database. The live GitHub Pages browser permission prompt and a timeout condition were not exercised in this environment. The backend CORS test confirms the hosted origin is allowed; users may still need to grant local-network access in their browser.
