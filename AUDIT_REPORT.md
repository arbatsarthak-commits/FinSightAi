# Audit Report

## Actual Findings

| Area | Finding | Root Cause |
|---|---|---|
| Runtime entry point | Streamlit app was active while no unified React/FastAPI runtime existed | Two disconnected UI generations |
| FastAPI | Missing from the original environment | Streamlit-only dependency set |
| Mistral prompt | `.format()` collided with JSON braces | Prompt treated invoice JSON braces as Python format fields |
| Pydantic | Null item descriptions could fail validation | `description` was a required string |
| Database | Existing database had no `source_hash` column | Schema migration was not implemented |
| Analytics | Dashboard totals mixed approved and pending records | SQL omitted approval-status filters |
| Chart API | `px.donut` was unsupported | Streamlit implementation used a Plotly Express API that does not exist |
| File handling | Upload names could collide or escape storage assumptions | Legacy implementation used direct user filenames |
| SQL | Assistant relied on string patterns | SQL validation needed authorizer restrictions |
| Frontend structure | React pages were nested and invisible to routes | Components were declared inside `processFile` before TypeScript route cleanup |
| Dependencies | Streamlit and UTF-16 `requirement.txt` remained | Duplicate dependency files |
| License | No repository license was present | Permission and redistribution status cannot be established |

## Backup

The existing SQLite database was copied to `ocr_master_table.backup-20261122.db` before migration.

## Migration Result

FastAPI API code, React/TypeScript routes and local Windows startup scripts are now present. Legacy Streamlit files and dependency declarations have been removed.

## Security Review Fixes

- Pairing authentication now fails closed if no 32-character token is configured.
- Private invoice, preview, status, analytics, assistant and report routes require pairing authentication.
- Local startup creates a random token outside the repository; the frontend requests it interactively and holds it in memory only.
- Invoice approval now rechecks processing status, required fields, financial validation and duplicate invoice numbers server-side.
- Editing any invoice returns it to `Pending` approval.
- CSV exports neutralize formula-leading text values.
- Upload and assistant endpoints are rate-limited; local server exceptions are logged without exposing internal details to API callers.
- Docker now uses separate FastAPI and Nginx frontend images, persistent database storage and loopback-only host ports.
