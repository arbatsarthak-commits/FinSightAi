import hashlib
import json
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import Any, Callable

from config import DB_PATH, MAX_UPLOAD_BYTES
from backend.database.database import (
    initialize_database,
    record_performance_metrics,
    save_extracted_invoice,
)
from backend.ocr.ocr_service import extract_document
from backend.services.invoice_extractor import extract_invoice_from_ocr
from backend.validation.validation_engine import validate_invoice


class InvoiceProcessingError(RuntimeError):
    pass


_processing_lock = threading.Lock()
_REQUIRED_CONFIDENCE = 0.75
_REQUIRED_FIELDS = ("invoice_number", "invoice_date", "vendor_name", "grand_total")


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _enrichment_candidates(invoice: dict, confidence: dict[str, float]) -> list[str]:
    candidates = [
        field for field in _REQUIRED_FIELDS
        if not invoice.get(field) or confidence.get(field, 0.0) < _REQUIRED_CONFIDENCE
    ]
    if not invoice.get("items"):
        candidates.append("line_items")
    elif any(item.get("category") in (None, "", "Other") for item in invoice["items"]):
        candidates.append("categories")
    return candidates


def _apply_confidence_validation(
    validation: dict, invoice: dict, confidence: dict[str, float]
) -> dict:
    validation = {
        **validation,
        "warnings": list(validation.get("warnings", [])),
        "missing_fields": list(validation.get("missing_fields", [])),
    }
    for field in _REQUIRED_FIELDS:
        value = invoice.get(field)
        if value and confidence.get(field, 0.0) < _REQUIRED_CONFIDENCE:
            validation["warnings"].append(
                f"OCR confidence for {field.replace('_', ' ')} is below the review threshold."
            )
    if not invoice.get("items"):
        validation["warnings"].append(
            "No invoice line items were detected; review line-item extraction."
        )
    if validation.get("errors"):
        validation["status"] = "Validation Failed"
    elif validation["warnings"] or validation["missing_fields"]:
        validation["status"] = "Needs Attention"
    else:
        validation["status"] = "Verified"
    return validation


def _metric_rows(performance: dict[str, Any]) -> list[dict[str, Any]]:
    stages = {
        "upload": "upload_seconds",
        "file_validation": "file_validation_seconds",
        "duplicate_detection": "duplicate_detection_seconds",
        "pdf_conversion": "pdf_conversion_seconds",
        "image_preprocessing": "preprocessing_seconds",
        "ocr": "ocr_seconds",
        "ocr_cache_lookup": "ocr_cache_lookup_seconds",
        "deterministic_extraction": "deterministic_extraction_seconds",
        "financial_validation": "financial_validation_seconds",
        "database_save": "database_save_seconds",
    }
    return [
        {"stage": stage, "duration_seconds": performance[key]}
        for stage, key in stages.items()
        if isinstance(performance.get(key), (int, float))
    ]


def process_invoice(
    source: str | Path,
    stage_callback: Callable[[str, str, str | None], None] | None = None,
    upload_seconds: float = 0.0,
) -> dict:
    source = Path(source)
    performance: dict[str, Any] = {"upload_seconds": round(max(upload_seconds, 0.0), 4)}
    stages: dict[str, str] = {}
    started = time.perf_counter()

    def report(stage: str, status: str, detail: str | None = None) -> None:
        stages[stage] = status
        if stage_callback:
            stage_callback(stage, status, detail)

    with _processing_lock:
        report("File validation", "Processing")
        stage_started = time.perf_counter()
        suffix = source.suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png", ".pdf"}:
            raise InvoiceProcessingError("Unsupported file type. Use JPG, JPEG, PNG or PDF.")
        if not source.is_file():
            raise InvoiceProcessingError("Uploaded file not found.")
        size = source.stat().st_size
        if size == 0:
            raise InvoiceProcessingError("The uploaded file is empty.")
        if size > MAX_UPLOAD_BYTES:
            maximum_mb = MAX_UPLOAD_BYTES // (1024 * 1024)
            raise InvoiceProcessingError(f"The uploaded file exceeds the {maximum_mb} MB limit.")
        performance["file_validation_seconds"] = round(time.perf_counter() - stage_started, 4)
        report("File validation", "Complete")

        report("Duplicate detection", "Processing")
        stage_started = time.perf_counter()
        source_hash = file_sha256(source)
        initialize_database(DB_PATH)
        with closing(sqlite3.connect(DB_PATH)) as connection:
            duplicate = connection.execute(
                """SELECT id, validation_status, processing_status
                   FROM invoices WHERE source_hash = ? LIMIT 1""",
                (source_hash,),
            ).fetchone()
        performance["duplicate_detection_seconds"] = round(time.perf_counter() - stage_started, 4)
        report("Duplicate detection", "Complete")
        if duplicate:
            performance["total_processing_seconds"] = round(time.perf_counter() - started, 4)
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
                "enrichment_recommended": [],
            }

        ocr = extract_document(source, on_stage=report)
        if not ocr["text"].strip():
            raise InvoiceProcessingError("OCR did not detect readable invoice text.")
        performance.update(ocr.pop("performance", {}))

        report("OCR text cleanup", "Processing")
        stage_started = time.perf_counter()
        ocr["text"] = "\n".join(
            " ".join(line.split()) for line in ocr["text"].splitlines() if line.strip()
        )
        performance["ocr_text_cleanup_seconds"] = round(time.perf_counter() - stage_started, 4)
        report("OCR text cleanup", "Complete")

        report("Deterministic extraction", "Processing")
        stage_started = time.perf_counter()
        extraction = extract_invoice_from_ocr(ocr)
        invoice = extraction["invoice"]
        evidence = extraction["evidence"]
        confidence = extraction["confidence"]
        performance["deterministic_extraction_seconds"] = round(time.perf_counter() - stage_started, 4)
        report("Deterministic extraction", "Complete")

        report("Invoice-number duplicate check", "Processing")
        stage_started = time.perf_counter()
        duplicate = None
        invoice_number = invoice.get("invoice_number")
        if invoice_number:
            with closing(sqlite3.connect(DB_PATH)) as connection:
                vendor_gstin = invoice.get("vendor_gstin")
                vendor_name = invoice.get("vendor_name")
                invoice_date = invoice.get("invoice_date")
                if vendor_gstin:
                    duplicate = connection.execute(
                        """SELECT id, validation_status, processing_status
                           FROM invoices WHERE lower(trim(invoice_number)) = lower(trim(?))
                             AND lower(trim(vendor_gstin)) = lower(trim(?)) LIMIT 1""",
                        (invoice_number, vendor_gstin),
                    ).fetchone()
                elif vendor_name:
                    duplicate = connection.execute(
                        """SELECT id, validation_status, processing_status
                           FROM invoices WHERE lower(trim(invoice_number)) = lower(trim(?))
                             AND lower(trim(vendor_name)) = lower(trim(?))
                             AND COALESCE(invoice_date, '') = COALESCE(?, '') LIMIT 1""",
                        (invoice_number, vendor_name, invoice_date),
                    ).fetchone()
                else:
                    duplicate = connection.execute(
                        """SELECT id, validation_status, processing_status
                           FROM invoices WHERE lower(trim(invoice_number)) = lower(trim(?))
                           LIMIT 1""",
                        (invoice_number,),
                    ).fetchone()
        performance["invoice_number_duplicate_check_seconds"] = round(time.perf_counter() - stage_started, 4)
        report("Invoice-number duplicate check", "Complete")
        if duplicate:
            performance["total_processing_seconds"] = round(time.perf_counter() - started, 4)
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
                "enrichment_recommended": [],
            }

        report("Financial validation", "Processing")
        stage_started = time.perf_counter()
        validation = _apply_confidence_validation(
            validate_invoice(invoice), invoice, confidence
        )
        performance["financial_validation_seconds"] = round(time.perf_counter() - stage_started, 4)
        report("Financial validation", "Complete")
        processing_status = (
            "Processed" if validation["status"] == "Verified" else "Needs Attention"
        )
        enrichment_candidates = _enrichment_candidates(invoice, confidence)

        report("Database save", "Processing")
        stage_started = time.perf_counter()
        invoice_id = save_extracted_invoice(
            DB_PATH,
            invoice,
            source.name,
            validation,
            json.dumps(invoice, ensure_ascii=False),
            processing_status=processing_status,
            source_hash=source_hash,
            ocr_text=ocr["text"],
            ocr_words=ocr.get("words", []),
            field_evidence=evidence,
            field_confidence=confidence,
            item_evidence=evidence.get("items", []),
            enrichment_status="queued" if enrichment_candidates else "not_needed",
        )
        performance["database_save_seconds"] = round(time.perf_counter() - stage_started, 4)
        report("Database save", "Complete")
        performance["total_processing_seconds"] = round(time.perf_counter() - started, 4)
        performance["total_end_to_end_seconds"] = round(
            performance["upload_seconds"] + performance["total_processing_seconds"], 4
        )
        timed_stages = {
            "File validation": "file_validation_seconds",
            "Duplicate detection": "duplicate_detection_seconds",
            "PDF conversion": "pdf_conversion_seconds",
            "OpenCV preprocessing": "preprocessing_seconds",
            "Tesseract OCR": "ocr_seconds",
            "Deterministic extraction": "deterministic_extraction_seconds",
            "Financial validation": "financial_validation_seconds",
            "Invoice-number duplicate check": "invoice_number_duplicate_check_seconds",
            "Database save": "database_save_seconds",
        }
        slowest_stage = max(
            timed_stages,
            key=lambda stage: performance.get(timed_stages[stage], 0.0),
        )
        record_performance_metrics(
            DB_PATH,
            _metric_rows(performance),
            invoice_id=invoice_id,
            request_id=source_hash,
        )

    return {
        "invoice_id": invoice_id,
        "invoice": invoice,
        "evidence": evidence,
        "field_confidence": confidence,
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
        "enrichment_recommended": enrichment_candidates,
    }
