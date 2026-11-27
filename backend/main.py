import copy
import hashlib
import io
import json
import logging
import os
import secrets
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError

from config import (
    APP_ENV,
    DB_PATH,
    INVOICE_DATA_DIR,
    LAYOUTLM_MODEL,
    MAX_UPLOAD_BYTES,
)
from backend.database.database import (
    initialize_database,
    get_dashboard_data,
    get_invoice_details,
    load_processing_jobs,
    record_performance_metrics,
    save_processing_job,
    update_invoice_enrichment,
)
from backend.services.invoice_pipeline import process_invoice, InvoiceProcessingError
from backend.llm.mistral_service import ollama_status, suggest_invoice_enrichment
from backend.ocr.ocr_service import check_tesseract, validate_document_file
from backend.services.chat_assistant import answer_question
from backend.models.invoice import InvoiceData
from backend.validation.validation_engine import validate_invoice


PAIRING_TOKEN = os.getenv("LOCAL_API_TOKEN", "")
DATA_DIR = INVOICE_DATA_DIR
DATA_DIR.mkdir(parents=True, exist_ok=True)
initialize_database(DB_PATH)
logger = logging.getLogger(__name__)
_processing_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="invoice-processing")
_enrichment_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="invoice-ai-enrichment")
_processing_jobs: dict[str, dict] = {}
_active_upload_jobs: dict[str, str] = {}
_active_upload_hashes: dict[str, str] = {}
_upload_timings: dict[str, float] = {}
_processing_jobs_lock = threading.RLock()


for _job in load_processing_jobs(DB_PATH, time.time() - 3600):
    if _job["status"] in {"queued", "processing"}:
        _job.update(
            status="failed",
            current_stage="Interrupted",
            error="Backend restarted during processing. Submit the upload again to retry.",
            updated_at=time.time(),
        )
        save_processing_job(DB_PATH, _job)
    _processing_jobs[_job["job_id"]] = _job


@asynccontextmanager
async def lifespan(_app):
    if len(PAIRING_TOKEN) < 32:
        raise RuntimeError(
            "LOCAL_API_TOKEN must be configured with at least 32 characters before startup."
        )
    try:
        yield
    finally:
        _processing_executor.shutdown(wait=False, cancel_futures=True)
        _enrichment_executor.shutdown(wait=False, cancel_futures=True)


app = FastAPI(title="Invoice Intelligence API", version="1.0.0", lifespan=lifespan)
frontend_origins = set()
if APP_ENV != "production":
    frontend_origins.update(
        {
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "https://arbatsarthak-commits.github.io",
        }
    )
frontend_origins.update(
    origin.strip()
    for origin in os.getenv("FRONTEND_ORIGINS", "").split(",")
    if origin.strip()
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(frontend_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Pairing-Token"],
)


@app.middleware("http")
async def prevent_api_cache(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


def require_pairing(x_pairing_token: Optional[str] = Header(default=None)):
    if not PAIRING_TOKEN or not x_pairing_token or not secrets.compare_digest(
        x_pairing_token, PAIRING_TOKEN
    ):
        raise HTTPException(status_code=401, detail="A valid local pairing token is required.")


_rate_buckets: dict[tuple[str, str], tuple[float, int]] = {}


def enforce_rate_limit(scope: str, client_host: str, limit: int = 20) -> None:
    now = time.monotonic()
    key = (scope, client_host)
    window_start, count = _rate_buckets.get(key, (now, 0))
    if now - window_start >= 60:
        window_start, count = now, 0
    if count >= limit:
        raise HTTPException(status_code=429, detail="Too many requests. Try again shortly.")
    _rate_buckets[key] = (window_start, count + 1)


def csv_safe(value):
    if not isinstance(value, str):
        return value
    probe = value.lstrip(" \t\r\n")
    if probe.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/system/status")
def system_status(x_pairing_token: Optional[str] = Header(default=None)):
    require_pairing(x_pairing_token)
    ollama = ollama_status()
    try:
        tesseract_version = check_tesseract()
        ocr_status = "available"
    except Exception:
        tesseract_version = None
        ocr_status = "unavailable"
    return {
        "backend": "available",
        "database": "available" if DB_PATH.exists() else "missing",
        "database_backend": "sqlite",
        "environment": APP_ENV,
        "file_storage_backend": "filesystem",
        "file_storage_path_configured": DATA_DIR.is_dir(),
        "max_upload_bytes": MAX_UPLOAD_BYTES,
        "ocr": ocr_status,
        "tesseract_version": tesseract_version,
        "ollama": ollama,
        "layoutlm": "configured" if LAYOUTLM_MODEL else "not configured",
        "layoutlm_checkpoint": bool(LAYOUTLM_MODEL),
    }


@app.post("/api/invoices/upload")
async def upload_invoice(request: Request, file: UploadFile = File(...),
                         x_pairing_token: Optional[str] = Header(default=None),
                         ):
    require_pairing(x_pairing_token)
    if request is not None:
        enforce_rate_limit("upload", request.client.host, limit=10)
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".pdf"}:
        raise HTTPException(status_code=415, detail="Use JPG, JPEG, PNG or PDF.")
    safe_name = f"{secrets.token_hex(8)}{suffix}"
    destination = DATA_DIR / safe_name
    started = time.perf_counter()
    size = 0
    try:
        with destination.open("wb") as output:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    maximum_mb = MAX_UPLOAD_BYTES // (1024 * 1024)
                    raise HTTPException(
                        status_code=413,
                        detail=f"The file exceeds the {maximum_mb} MB limit.",
                    )
                output.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await file.close()
    if size == 0:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    try:
        validate_document_file(destination)
    except ValueError as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    upload_seconds = round(time.perf_counter() - started, 4)
    with _processing_jobs_lock:
        _upload_timings[safe_name] = upload_seconds
    return {
        "upload_id": safe_name,
        "filename": file.filename,
        "size": size,
        "upload_seconds": upload_seconds,
        "preview_url": f"/api/invoices/upload/{safe_name}",
    }


@app.get("/api/invoices/upload/{filename}")
def uploaded_preview(filename: str, x_pairing_token: Optional[str] = Header(default=None)):
    require_pairing(x_pairing_token)
    if "/" in filename or "\\" in filename or Path(filename).name != filename:
        raise HTTPException(status_code=400, detail="Invalid filename.")
    path = DATA_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Uploaded file not found.")
    suffix = path.suffix.lower()
    media = {
        ".pdf": "application/pdf",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
    }.get(suffix, "application/octet-stream")
    return StreamingResponse(path.open("rb"), media_type=media)


@app.post("/api/invoices/{upload_id}/analyze")
def analyze_invoice(upload_id: str, request: Request,
                    x_pairing_token: Optional[str] = Header(default=None)):
    require_pairing(x_pairing_token)
    if request is not None:
        enforce_rate_limit("analyze", request.client.host, limit=10)
    if "/" in upload_id or "\\" in upload_id or Path(upload_id).name != upload_id:
        raise HTTPException(status_code=400, detail="Invalid upload identifier.")
    path = DATA_DIR / upload_id
    if not path.exists():
        raise HTTPException(status_code=404, detail="Uploaded file not found.")
    source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    with _processing_jobs_lock:
        expired_jobs = [
            job_id for job_id, job in _processing_jobs.items()
            if job["status"] in {"complete", "failed"}
            and time.time() - job.get("created_at", time.time()) > 3600
        ]
        for expired_job in expired_jobs:
            _processing_jobs.pop(expired_job, None)
        active_job = _active_upload_jobs.get(upload_id)
        if active_job:
            return JSONResponse(
                status_code=202,
                content={
                    "job_id": active_job,
                    "status": _processing_jobs[active_job]["status"],
                },
            )
        active_job = _active_upload_hashes.get(source_hash)
        if active_job:
            return JSONResponse(
                status_code=202,
                content={
                    "job_id": active_job,
                    "status": _processing_jobs[active_job]["status"],
                },
            )
        job_id = str(uuid.uuid4())
        _processing_jobs[job_id] = {
            "job_id": job_id,
            "upload_id": upload_id,
            "status": "queued",
            "current_stage": "Queued",
            "stages": {},
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        _active_upload_jobs[upload_id] = job_id
        _active_upload_hashes[source_hash] = job_id
        upload_seconds = _upload_timings.pop(upload_id, 0.0)
        queued_jobs = sorted(
            (
                item for item in _processing_jobs.values()
                if item["status"] == "queued"
            ),
            key=lambda item: item["created_at"],
        )
        queue_position = next(
            (index for index, item in enumerate(queued_jobs, start=1) if item["job_id"] == job_id),
            1,
        )
        queued_record = copy.deepcopy(_processing_jobs[job_id])
    save_processing_job(DB_PATH, queued_record)
    _processing_executor.submit(_run_processing_job, job_id, upload_id, path, upload_seconds)
    return JSONResponse(
        status_code=202,
        content={"job_id": job_id, "status": "queued", "queue_position": queue_position},
    )


def _run_processing_job(job_id: str, upload_id: str, path: Path, upload_seconds: float) -> None:
    def update_stage(stage: str, status: str, detail: str | None) -> None:
        with _processing_jobs_lock:
            job = _processing_jobs[job_id]
            job["status"] = "processing"
            job["current_stage"] = stage
            job["stages"][stage] = {"status": status, "detail": detail}
            job["updated_at"] = time.time()
            snapshot = copy.deepcopy(job)
        save_processing_job(DB_PATH, snapshot)

    try:
        result = process_invoice(
            path, stage_callback=update_stage, upload_seconds=upload_seconds
        )
        if result.get("enrichment_recommended") and result.get("invoice_id"):
            result["enrichment_status"] = "queued"
            try:
                _enrichment_executor.submit(
                    _run_optional_enrichment,
                    result["invoice_id"],
                    result.get("ocr", {}).get("text", ""),
                    result["enrichment_recommended"],
                )
            except RuntimeError as exc:
                logger.warning("Could not queue optional AI enrichment: %s", exc)
                update_invoice_enrichment(
                    DB_PATH,
                    result["invoice_id"],
                    status="unavailable",
                    error=str(exc),
                )
        else:
            result["enrichment_status"] = "not_needed"
        with _processing_jobs_lock:
            _processing_jobs[job_id].update(
                status="complete", current_stage="Complete", result=result,
                updated_at=time.time(),
            )
            snapshot = copy.deepcopy(_processing_jobs[job_id])
        save_processing_job(DB_PATH, snapshot)
    except InvoiceProcessingError as exc:
        with _processing_jobs_lock:
            _processing_jobs[job_id].update(
                status="failed", current_stage="Failed", error=str(exc),
                updated_at=time.time(),
            )
            snapshot = copy.deepcopy(_processing_jobs[job_id])
        save_processing_job(DB_PATH, snapshot)
    except (RuntimeError, ValueError, TimeoutError, FileNotFoundError) as exc:
        logger.warning("Invoice processing stopped for upload %s: %s", upload_id, exc)
        with _processing_jobs_lock:
            _processing_jobs[job_id].update(
                status="failed", current_stage="Failed", error=str(exc),
                updated_at=time.time(),
            )
            snapshot = copy.deepcopy(_processing_jobs[job_id])
        save_processing_job(DB_PATH, snapshot)
    except Exception:
        logger.exception("Invoice processing failed for upload %s", upload_id)
        with _processing_jobs_lock:
            _processing_jobs[job_id].update(
                status="failed",
                current_stage="Failed",
                error="Invoice processing failed. Check local service status and retry.",
                updated_at=time.time(),
            )
            snapshot = copy.deepcopy(_processing_jobs[job_id])
        save_processing_job(DB_PATH, snapshot)
    finally:
        with _processing_jobs_lock:
            _active_upload_jobs.pop(upload_id, None)
            for source_hash, active_job in list(_active_upload_hashes.items()):
                if active_job == job_id:
                    _active_upload_hashes.pop(source_hash, None)


def _run_optional_enrichment(
    invoice_id: int, raw_text: str, requested_fields: list[str]
) -> None:
    started = time.perf_counter()
    status = "complete"
    details = {}
    try:
        suggestions, model_metrics = suggest_invoice_enrichment(raw_text, requested_fields)
        status = "complete" if suggestions else "no_suggestions"
        details = model_metrics
        update_invoice_enrichment(
            DB_PATH,
            invoice_id,
            status=status,
            suggestions=suggestions,
        )
    except Exception as exc:
        status = "unavailable" if "not installed" in str(exc).lower() or "cannot reach ollama" in str(exc).lower() else "failed"
        logger.warning("Optional AI enrichment failed for invoice %s: %s", invoice_id, exc)
        try:
            update_invoice_enrichment(DB_PATH, invoice_id, status=status, error=str(exc))
        except Exception:
            logger.exception("Could not persist AI enrichment failure for invoice %s", invoice_id)
    finally:
        try:
            record_performance_metrics(
                DB_PATH,
                [{
                    "stage": "optional_ai_enrichment",
                    "duration_seconds": time.perf_counter() - started,
                    "status": status,
                    "details": details,
                }],
                invoice_id=invoice_id,
                request_id=f"enrichment-{invoice_id}",
            )
        except Exception:
            logger.exception("Could not persist AI enrichment timings for invoice %s", invoice_id)


@app.get("/api/processing/{job_id}")
def processing_status(job_id: str,
                      x_pairing_token: Optional[str] = Header(default=None)):
    require_pairing(x_pairing_token)
    with _processing_jobs_lock:
        job = _processing_jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Processing job not found.")
        result = copy.deepcopy(job)
        queued = sorted(
            (
                item for item in _processing_jobs.values()
                if item["status"] == "queued"
            ),
            key=lambda item: item["created_at"],
        )
        result["queue_position"] = next(
            (index for index, item in enumerate(queued, start=1) if item["job_id"] == job_id),
            None,
        )
        return result


@app.get("/api/invoices")
def list_invoices(search: Optional[str] = None,
                  status: Optional[str] = None,
                  x_pairing_token: Optional[str] = Header(default=None)):
    require_pairing(x_pairing_token)
    with sqlite3.connect(DB_PATH) as connection:
        connection.row_factory = sqlite3.Row
        query = """SELECT id, invoice_number, invoice_date, due_date, vendor_name,
                          vendor_gstin, customer_name, customer_gstin, grand_total,
                          subtotal, total_tax, currency, payment_status, source_file,
                          validation_status, processing_status, created_at
                   FROM invoices"""
        parameters = []
        clauses = []
        if search:
            clauses.append("(invoice_number LIKE ? OR vendor_name LIKE ? OR source_file LIKE ?)")
            term = f"%{search}%"
            parameters.extend([term, term, term])
        if status:
            clauses.append("(validation_status = ? OR processing_status = ?)")
            parameters.extend([status, status])
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY id DESC"
        rows = connection.execute(query, parameters).fetchall()
    return [dict(row) for row in rows]


@app.get("/api/invoices/{invoice_id}")
def invoice_details(invoice_id: int,
                    x_pairing_token: Optional[str] = Header(default=None)):
    require_pairing(x_pairing_token)
    details = get_invoice_details(DB_PATH, invoice_id)
    if not details:
        raise HTTPException(status_code=404, detail="Invoice not found.")
    details["invoice"].pop("approval_status", None)
    details["invoice"].pop("corrected_data", None)
    return details


@app.put("/api/invoices/{invoice_id}")
def correct_invoice(invoice_id: int, payload: dict,
                    x_pairing_token: Optional[str] = Header(default=None)):
    require_pairing(x_pairing_token)
    if not isinstance(payload, dict) or not payload:
        raise HTTPException(status_code=400, detail="Provide at least one invoice field to correct.")
    allowed_fields = {
        "invoice_number", "invoice_date", "due_date", "vendor_name", "vendor_gstin",
        "customer_name", "customer_gstin", "subtotal", "cgst", "sgst", "igst",
        "total_tax", "grand_total", "currency", "payment_status",
    }
    if set(payload) - allowed_fields:
        raise HTTPException(status_code=422, detail="One or more invoice fields cannot be edited.")
    with sqlite3.connect(DB_PATH) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT extracted_data, corrected_data FROM invoices WHERE id = ?",
            (invoice_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Invoice not found.")
    try:
        existing_data = json.loads(row["corrected_data"] or row["extracted_data"] or "{}")
        if not isinstance(existing_data, dict):
            raise ValueError("Stored invoice data is invalid.")
        invoice = InvoiceData.model_validate({**existing_data, **payload})
    except (ValidationError, json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"Invoice correction is invalid: {exc}") from exc
    corrected = invoice.model_dump()
    validation = validate_invoice(corrected)
    processing_status = "Processed" if validation["status"] == "Verified" else "Needs Attention"
    with sqlite3.connect(DB_PATH) as connection:
        connection.execute(
            """UPDATE invoices SET invoice_number=?, invoice_date=?, due_date=?,
               vendor_name=?, vendor_gstin=?, customer_name=?, customer_gstin=?,
               subtotal=?, cgst=?, sgst=?, igst=?, total_tax=?, grand_total=?,
               currency=?, payment_status=?, corrected_data=?, validation_status=?,
               processing_status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?""",
            (
                corrected["invoice_number"], corrected["invoice_date"], corrected["due_date"],
                corrected["vendor_name"], corrected["vendor_gstin"], corrected["customer_name"],
                corrected["customer_gstin"], corrected["subtotal"], corrected["cgst"],
                corrected["sgst"], corrected["igst"], corrected["total_tax"],
                corrected["grand_total"], corrected["currency"], corrected["payment_status"],
                json.dumps(corrected, ensure_ascii=False), validation["status"],
                processing_status, invoice_id,
            ),
        )
        connection.commit()
    return {
        "invoice_id": invoice_id,
        "invoice": corrected,
        "validation": validation,
        "processing_status": processing_status,
    }


@app.delete("/api/invoices/{invoice_id}")
def delete_invoice(invoice_id: int,
                   x_pairing_token: Optional[str] = Header(default=None)):
    require_pairing(x_pairing_token)
    source_file = None
    with sqlite3.connect(DB_PATH) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        row = connection.execute(
            "SELECT source_file FROM invoices WHERE id = ?", (invoice_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Invoice not found.")
        source_file = row[0]
        connection.execute("DELETE FROM invoices WHERE id = ?", (invoice_id,))
        remaining = (
            connection.execute(
                "SELECT COUNT(*) FROM invoices WHERE source_file = ?", (source_file,)
            ).fetchone()[0]
            if source_file else 0
        )
        connection.commit()
    if source_file and not remaining and Path(source_file).name == source_file:
        stored_path = (DATA_DIR / source_file).resolve()
        if stored_path.parent == DATA_DIR.resolve():
            stored_path.unlink(missing_ok=True)
    return {"deleted": True, "invoice_id": invoice_id}


@app.get("/api/analytics/overview")
def analytics_overview(x_pairing_token: Optional[str] = Header(default=None)):
    require_pairing(x_pairing_token)
    return get_dashboard_data(DB_PATH)


@app.get("/api/analytics/monthly")
def analytics_monthly(x_pairing_token: Optional[str] = Header(default=None)):
    require_pairing(x_pairing_token)
    data = get_dashboard_data(DB_PATH)
    return data["monthly"]


@app.get("/api/analytics/categories")
def analytics_categories(x_pairing_token: Optional[str] = Header(default=None)):
    require_pairing(x_pairing_token)
    data = get_dashboard_data(DB_PATH)
    return data["categories"]


@app.get("/api/analytics/vendors")
def analytics_vendors(x_pairing_token: Optional[str] = Header(default=None)):
    require_pairing(x_pairing_token)
    data = get_dashboard_data(DB_PATH)
    return data["vendors"]


@app.post("/api/assistant/query")
def assistant_query(payload: dict, request: Request,
                    x_pairing_token: Optional[str] = Header(default=None)):
    require_pairing(x_pairing_token)
    if request is not None:
        enforce_rate_limit("assistant", request.client.host, limit=10)
    question = str(payload.get("question", "")).strip()
    if not question:
        raise HTTPException(status_code=400, detail="A question is required.")
    history = payload.get("history", [])
    if not isinstance(history, list):
        raise HTTPException(status_code=400, detail="Conversation history must be a list.")
    if len(question) > 1000:
        raise HTTPException(status_code=413, detail="Question exceeds the 1000-character limit.")
    history = [
        {
            "role": entry.get("role"),
            "content": str(entry.get("content", ""))[:1000],
            "context": {
                **{
                    key: value[:120]
                    for key, value in entry.get("context", {}).items()
                    if key in {"vendor", "category", "invoice_number"}
                    and isinstance(value, str)
                },
                **(
                    {"invoice_id": entry["context"]["invoice_id"]}
                    if isinstance(entry.get("context"), dict)
                    and isinstance(entry["context"].get("invoice_id"), int)
                    and not isinstance(entry["context"]["invoice_id"], bool)
                    and entry["context"]["invoice_id"] > 0
                    else {}
                ),
            } if isinstance(entry.get("context"), dict) else {},
        }
        for entry in history[-8:]
        if isinstance(entry, dict) and entry.get("role") in {"user", "assistant"}
    ]
    try:
        result = answer_question(DB_PATH, question, history)
        return {"question": question, **result}
    except sqlite3.DatabaseError:
        logger.exception("Expense assistant request failed")
        raise HTTPException(status_code=500, detail="Assistant database query failed.")


@app.get("/api/reports/export")
def export_report(x_pairing_token: Optional[str] = Header(default=None)):
    require_pairing(x_pairing_token)
    with sqlite3.connect(DB_PATH) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """SELECT invoice_number, invoice_date, vendor_name, grand_total,
                      total_tax, validation_status, processing_status
               FROM invoices ORDER BY id DESC"""
        ).fetchall()
    output = io.StringIO()
    import csv
    writer = csv.writer(output)
    writer.writerow(["invoice_number","invoice_date","vendor_name","grand_total","total_tax",
                     "validation_status","processing_status"])
    for row in rows:
        writer.writerow([
            csv_safe(row[key])
            for key in ("invoice_number", "invoice_date", "vendor_name", "grand_total",
                        "total_tax", "validation_status", "processing_status")
        ])
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="invoice_report.csv"'},
    )
