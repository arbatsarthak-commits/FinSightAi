import hashlib
import json
import re
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import Callable

from config import DB_PATH
from backend.database.database import initialize_database, save_extracted_invoice
from backend.llm.mistral_service import extract_invoice_with_metrics
from backend.ocr.ocr_service import extract_document
from backend.validation.validation_engine import validate_invoice


class InvoiceProcessingError(RuntimeError):
    pass


_processing_lock = threading.Lock()


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def process_invoice(
    source: str | Path,
    stage_callback: Callable[[str, str, str | None], None] | None = None,
    upload_seconds: float = 0.0,
) -> dict:
    source = Path(source)
    stages = {}
    performance = {"upload_seconds": round(upload_seconds, 4)}
    started = time.perf_counter()

    def report(stage: str, status: str, detail: str | None = None) -> None:
        stages[stage] = status
        if stage_callback:
            stage_callback(stage, status, detail)

    with _processing_lock:
        report("File validation", "Processing")
        validation_started = time.perf_counter()
        suffix = source.suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png", ".pdf"}:
            raise InvoiceProcessingError("Unsupported file type. Use JPG, JPEG, PNG or PDF.")
        if not source.is_file():
            raise InvoiceProcessingError("Uploaded file not found.")
        size = source.stat().st_size
        if size == 0:
            raise InvoiceProcessingError("The uploaded file is empty.")
        if size > 20 * 1024 * 1024:
            raise InvoiceProcessingError("The uploaded file exceeds the 20 MB limit.")
        performance["file_validation_seconds"] = round(
            time.perf_counter() - validation_started, 4
        )
        report("File validation", "Complete")

        report("Duplicate detection", "Processing")
        duplicate_started = time.perf_counter()
        source_hash = file_sha256(source)
        initialize_database(DB_PATH)
        with closing(sqlite3.connect(DB_PATH)) as connection:
            duplicate = connection.execute(
                """SELECT id, validation_status, processing_status
                   FROM invoices WHERE source_hash = ? LIMIT 1""",
                (source_hash,),
            ).fetchone()
        performance["duplicate_detection_seconds"] = round(
            time.perf_counter() - duplicate_started, 4
        )
        report("Duplicate detection", "Complete")
        if duplicate:
            performance["total_processing_seconds"] = round(
                time.perf_counter() - started, 4
            )
            performance["total_end_to_end_seconds"] = round(
                performance["upload_seconds"] + performance["total_processing_seconds"], 4
            )
            return {
                "duplicate": True,
                "invoice_id": duplicate[0],
                "processing_status": duplicate[2],
                "validation": {
                    "status": duplicate[1],
                    "warnings": ["This file has already been processed."],
                    "errors": [],
                    "missing_fields": [],
                },
                "performance": performance,
                "slowest_stage": "Duplicate detection",
                "stages": stages,
                "auto_saved": False,
            }

        ocr = extract_document(source, on_stage=report)
        if not ocr["text"].strip():
            raise InvoiceProcessingError("OCR did not detect readable invoice text.")
        performance.update(ocr.pop("performance"))
        report("OCR text cleanup", "Processing")
        cleanup_started = time.perf_counter()
        cleaned_text = re.sub(r"[ \t]+", " ", ocr["text"])
        cleaned_text = re.sub(r"\n{3,}", "\n\n", cleaned_text).strip()
        ocr["text"] = cleaned_text
        performance["ocr_text_cleanup_seconds"] = round(
            time.perf_counter() - cleanup_started, 4
        )
        report("OCR text cleanup", "Complete")

        report("Mistral invoice extraction", "Processing")
        invoice_data, model_performance = extract_invoice_with_metrics(ocr["text"])
        performance.update(model_performance)
        invoice = invoice_data.model_dump()
        report("Mistral invoice extraction", "Complete")

        report("Invoice-number duplicate check", "Processing")
        duplicate_started = time.perf_counter()
        invoice_number = invoice.get("invoice_number")
        with closing(sqlite3.connect(DB_PATH)) as connection:
            duplicate = None
            if invoice_number:
                duplicate = connection.execute(
                    """SELECT id, validation_status, processing_status
                       FROM invoices
                       WHERE invoice_number IS NOT NULL
                         AND lower(trim(invoice_number)) = lower(trim(?))
                       LIMIT 1""",
                    (invoice_number,),
                ).fetchone()
        performance["invoice_number_duplicate_check_seconds"] = round(
            time.perf_counter() - duplicate_started, 4
        )
        report("Invoice-number duplicate check", "Complete")
        if duplicate:
            performance["total_processing_seconds"] = round(
                time.perf_counter() - started, 4
            )
            performance["total_end_to_end_seconds"] = round(
                performance["upload_seconds"] + performance["total_processing_seconds"], 4
            )
            return {
                "duplicate": True,
                "invoice_id": duplicate[0],
                "processing_status": duplicate[2],
                "validation": {
                    "status": duplicate[1],
                    "warnings": ["An invoice with this number has already been processed."],
                    "errors": [],
                    "missing_fields": [],
                },
                "performance": performance,
                "slowest_stage": "Invoice-number duplicate check",
                "stages": stages,
                "auto_saved": False,
            }

        report("Financial validation", "Processing")
        validation_started = time.perf_counter()
        validation = validate_invoice(invoice)
        performance["financial_validation_seconds"] = round(
            time.perf_counter() - validation_started, 4
        )
        report("Financial validation", "Complete")

        processing_status = (
            "Processed" if validation["status"] == "Verified" else "Needs Attention"
        )
        report("Database insertion", "Processing")
        insertion_started = time.perf_counter()
        invoice_id = save_extracted_invoice(
            DB_PATH,
            invoice,
            source.name,
            validation,
            json.dumps(invoice, ensure_ascii=False),
            processing_status=processing_status,
            source_hash=source_hash,
        )
        performance["database_insertion_seconds"] = round(
            time.perf_counter() - insertion_started, 4
        )
        report("Database insertion", "Complete")

    performance["total_processing_seconds"] = round(time.perf_counter() - started, 4)
    performance["total_end_to_end_seconds"] = round(
        performance["upload_seconds"] + performance["total_processing_seconds"], 4
    )
    timed_stages = {
        "File validation": "file_validation_seconds",
        "PDF conversion": "pdf_conversion_seconds",
        "OpenCV preprocessing": "preprocessing_seconds",
        "Tesseract OCR": "ocr_seconds",
        "Mistral inference": "mistral_inference_seconds",
        "Pydantic validation": "pydantic_validation_seconds",
        "Financial validation": "financial_validation_seconds",
        "File duplicate detection": "duplicate_detection_seconds",
        "Invoice-number duplicate check": "invoice_number_duplicate_check_seconds",
        "Database insertion": "database_insertion_seconds",
    }
    slowest_stage = max(
        timed_stages,
        key=lambda stage: performance.get(timed_stages[stage], 0.0),
    )
    return {
        "invoice_id": invoice_id,
        "invoice": invoice,
        "ocr": {
            "text": ocr["text"],
            "pages": ocr["pages"],
            "document": ocr.get(
                "document",
                {
                    "pages_total": len(ocr["pages"]),
                    "pages_processed": len(ocr["pages"]),
                    "partial": False,
                    "warning": None,
                },
            ),
        },
        "validation": validation,
        "processing_status": processing_status,
        "source": source.name,
        "source_hash": source_hash,
        "performance": performance,
        "slowest_stage": slowest_stage,
        "stages": stages,
        "auto_saved": True,
        "duplicate": False,
    }
