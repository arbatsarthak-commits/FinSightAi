from backend.database.database import get_dashboard_data, get_invoice_details
from backend.models.invoice import InvoiceData
from backend.services import invoice_pipeline


def _invoice(grand_total=118):
    return InvoiceData.model_validate({
        "invoice_number": "INV-PIPELINE",
        "invoice_date": "2026-11-23",
        "vendor_name": "Test vendor",
        "subtotal": 100,
        "cgst": 9,
        "sgst": 9,
        "igst": 0,
        "total_tax": 18,
        "grand_total": grand_total,
        "items": [{
            "description": "Service",
            "quantity": 1,
            "unit_price": 100,
            "taxable_value": 100,
            "amount": 100,
            "cgst": 9,
            "sgst": 9,
            "category": "Food",
        }],
    })


def _install_pipeline_fakes(monkeypatch, invoice=None):
    extraction_calls = []

    def fake_document(source, on_stage=None):
        if on_stage:
            on_stage("OpenCV preprocessing", "Complete", "Page 1")
            on_stage("Tesseract OCR", "Complete", "Page 1")
        return {
            "text": source.name,
            "pages": [{"page": 1, "text": source.name, "word_count": 1, "average_confidence": 90}],
            "performance": {
                "pdf_conversion_seconds": 0.0,
                "preprocessing_seconds": 0.01,
                "ocr_seconds": 0.02,
            },
        }

    def fake_extraction(raw_text):
        extraction_calls.append(raw_text)
        extracted = invoice or _invoice()
        return extracted, {
            "mistral_inference_seconds": 0.03,
            "pydantic_validation_seconds": 0.001,
        }

    monkeypatch.setattr(invoice_pipeline, "extract_document", fake_document)
    monkeypatch.setattr(invoice_pipeline, "extract_invoice_with_metrics", fake_extraction)
    return extraction_calls


def test_pipeline_saves_verified_invoice_and_skips_same_file_before_ocr(tmp_path, monkeypatch):
    monkeypatch.setattr(invoice_pipeline, "DB_PATH", tmp_path / "pipeline.db")
    extraction_calls = _install_pipeline_fakes(monkeypatch)
    first_file = tmp_path / "invoice.png"
    first_file.write_bytes(b"same invoice")

    result = invoice_pipeline.process_invoice(first_file, upload_seconds=0.005)

    assert result["auto_saved"] is True
    assert result["processing_status"] == "Processed"
    assert result["validation"]["status"] == "Verified"
    assert result["invoice"]["items"][0]["category"] == "food"
    assert result["performance"]["ocr_seconds"] == 0.02
    assert result["performance"]["upload_seconds"] == 0.005
    assert result["slowest_stage"] in {
        "File validation",
        "PDF conversion",
        "OpenCV preprocessing",
        "Tesseract OCR",
        "Mistral inference",
        "Pydantic validation",
        "Financial validation",
        "File duplicate detection",
        "Invoice-number duplicate check",
        "Database insertion",
    }
    assert get_invoice_details(invoice_pipeline.DB_PATH, result["invoice_id"])["invoice"][
        "processing_status"
    ] == "Processed"

    duplicate_file = tmp_path / "same-content.png"
    duplicate_file.write_bytes(first_file.read_bytes())
    duplicate = invoice_pipeline.process_invoice(duplicate_file)

    assert duplicate["duplicate"] is True
    assert duplicate["invoice_id"] == result["invoice_id"]
    assert len(extraction_calls) == 1


def test_invoice_number_duplicate_is_not_inserted(tmp_path, monkeypatch):
    monkeypatch.setattr(invoice_pipeline, "DB_PATH", tmp_path / "number-duplicate.db")
    _install_pipeline_fakes(monkeypatch)
    first_file = tmp_path / "first.png"
    second_file = tmp_path / "second.png"
    first_file.write_bytes(b"first invoice")
    second_file.write_bytes(b"same invoice number, different file")

    first = invoice_pipeline.process_invoice(first_file)
    second = invoice_pipeline.process_invoice(second_file)

    assert second["duplicate"] is True
    assert second["invoice_id"] == first["invoice_id"]
    assert second["slowest_stage"] == "Invoice-number duplicate check"
    assert get_dashboard_data(invoice_pipeline.DB_PATH)["summary"]["total_invoices"] == 1


def test_invalid_invoice_is_retained_and_excluded_from_financial_totals(tmp_path, monkeypatch):
    monkeypatch.setattr(invoice_pipeline, "DB_PATH", tmp_path / "invalid.db")
    _install_pipeline_fakes(monkeypatch, invoice=_invoice(grand_total=130))
    source = tmp_path / "invalid.png"
    source.write_bytes(b"financial mismatch")

    result = invoice_pipeline.process_invoice(source)
    dashboard = get_dashboard_data(invoice_pipeline.DB_PATH)

    assert result["processing_status"] == "Needs Attention"
    assert result["validation"]["status"] == "Validation Failed"
    assert dashboard["summary"]["total_invoices"] == 0
    assert dashboard["summary"]["total_expenses"] == 0
    assert dashboard["summary"]["needs_attention"] == 1
    assert get_invoice_details(invoice_pipeline.DB_PATH, result["invoice_id"])["invoice"][
        "processing_status"
    ] == "Needs Attention"
