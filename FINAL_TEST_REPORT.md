# Final Test Report

## Migration Summary

Current branch: `repair/debug-ui-2026`

The project has been migrated from Streamlit to a FastAPI and React/TypeScript application. Streamlit source files and dependency declarations were removed after migration.

## Test Matrix

| Test | Result | Evidence |
|---|---|---|
| FastAPI health | PASS | `/api/health` returned HTTP 200 and `{"status":"ok","database":"available"}` |
| System status | PASS | Tesseract 5.5.3 detected, Ollama reachable and Mistral available |
| SQLite analytics | PASS | `/api/analytics/overview` returned real database-backed summary |
| Unsupported upload | PASS | API rejected text uploads with HTTP 415 |
| OCR extraction | PASS | `OCR_image2.png`: 510 text characters, 84.16% average confidence |
| Mistral processing | PASS | Ollama and `mistral:latest` returned a structured invoice result |
| Financial validation | PASS | Unit test passed |
| Database insertion | PASS | SQLite save test passed |
| SQL safety | PASS | Mutation and restricted-table tests passed |
| React production build | PASS | Vite + TypeScript production build succeeded |
| Python pytest suite | PASS | 22 tests passed, including fail-closed auth, protected routes, approval policy, duplicate rejection and CSV formula handling |
| Docker Compose configuration | PASS | `docker compose config --quiet` succeeded with a valid pairing token |
| Docker image build | BLOCKED | Docker CLI is installed, but Docker Desktop Linux engine is not running (`dockerDesktopLinuxEngine` pipe unavailable) |
| Application restart | PASS | SQLite initialization preserved the database backup and existing database |
| JPG/PNG browser upload | NOT TESTED | No Playwright browser run was available in the implementation pass |
| PDF browser upload | NOT TESTED | PDF support is implemented but no browser integration run was executed |
| Browser approval workflow | NOT TESTED | React review controls exist; Playwright evidence is unavailable |
| CSV browser download | NOT TESTED | API export exists; browser download was not automated |
| Pairing token fail-closed | PASS | Startup rejects missing/short token; 401 tests cover private routes |
| Approval bypass | PASS | API rejects unverified, incomplete and duplicate records; verified record passes |
| CSV formula injection | PASS | API export prefixes formula-leading text with an apostrophe |
| LayoutLMv3 inference | BLOCKED | No fine-tuned checkpoint or labeled invoice dataset is available |

## Reproducible Commands

```powershell
.\.venv\Scripts\python.exe -m pytest -q
cd frontend
npm run build
.\start_all.ps1
```

## Files Inspected

Python modules, existing frontend files, database, dependencies, OCR, Mistral, validation, SQL assistant and deployment configuration.

## Remaining Limitations

- Browser-level Playwright journeys were not run.
- A fine-tuned LayoutLMv3 checkpoint was not supplied.
- GitHub Pages workflow cannot execute the local Python backend.
- Public users need a separate hosted backend for remote AI processing.
