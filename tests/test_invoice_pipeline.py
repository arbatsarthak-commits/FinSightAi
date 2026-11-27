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


def _install_pipeline_fakes(monkeypatch, invoice=None, confidence=None):
    extraction_calls = []

    def fake_document(source, on_stage=None):
        if on_stage:
            on_stage("OpenCV preprocessing", "Complete", "Page 1")
            on_stage("Tesseract OCR", "Complete", "Page 1")
        return {
            "text": "invoice evidence",
            "words": [{"text": "invoice", "confidence": 95, "left": 2, "top": 4}],
            "pages": [{"page": 1, "text": "invoice evidence", "word_count": 1, "average_confidence": 90}],
            "performance": {
                "pdf_conversion_seconds": 0.0,
                "preprocessing_seconds": 0.01,
                "ocr_seconds": 0.02,
            },
        }

    def fake_extraction(ocr):
        extraction_calls.append(ocr["text"])
        extracted = invoice or _invoice()
        fields = {
            field: 0.99 for field in (
                "invoice_number", "invoice_date", "vendor_name", "grand_total"
            )
        }
        fields["items"] = 0.99
        if confidence:
            fields.update(confidence)
        return {
            "invoice": extracted.model_dump(),
            "evidence": {
                "invoice_number": {"source": "tesseract", "line": "Invoice No: INV-PIPELINE"},
                "vendor_name": {
                    "source": "tesseract",
                    "line": "Test vendor",
                    "ocr_confidence": 0.44,
                    "pattern_reliability": 0.95,
                    "extraction_method": "layout heuristic",
                },
                "items": [{
                    "item": 1,
                    "fields": {"description": {"source": "tesseract", "line": "Service"}},
                    "confidence": 0.99,
                }],
            },
            "confidence": fields,
        }

    monkeypatch.setattr(invoice_pipeline, "extract_document", fake_document)
    monkeypatch.setattr(invoice_pipeline, "extract_invoice_from_ocr", fake_extraction)
    return extraction_calls


def test_pipeline_saves_deterministic_invoice_and_skips_same_file_before_ocr(tmp_path, monkeypatch):
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
    assert "mistral_inference_seconds" not in result["performance"]
    details = get_invoice_details(invoice_pipeline.DB_PATH, result["invoice_id"])
    assert details["invoice"]["processing_status"] == "Processed"
    assert details["invoice"]["ocr_text"] == "invoice evidence"
    assert details["invoice"]["field_evidence"]["invoice_number"]["source"] == "tesseract"
    assert details["items"][0]["evidence"]["confidence"] == 0.99

    duplicate_file = tmp_path / "same-content.png"
    duplicate_file.write_bytes(first_file.read_bytes())
    duplicate = invoice_pipeline.process_invoice(duplicate_file)

    assert duplicate["duplicate"] is True
    assert duplicate["invoice_id"] == result["invoice_id"]
    assert len(extraction_calls) == 1


def test_low_confidence_fields_are_saved_as_needs_attention(tmp_path, monkeypatch):
    monkeypatch.setattr(invoice_pipeline, "DB_PATH", tmp_path / "uncertain.db")
    _install_pipeline_fakes(monkeypatch, confidence={"vendor_name": 0.42})
    source = tmp_path / "uncertain.png"
    source.write_bytes(b"uncertain invoice")

    result = invoice_pipeline.process_invoice(source)

    assert result["processing_status"] == "Needs Attention"
    assert result["validation"]["status"] == "Needs Attention"
    assert any("vendor name" in warning for warning in result["validation"]["warnings"])
    reason = result["validation"]["confidence_reasons"]["vendor_name"]
    assert reason["required_threshold"] == 0.8
    assert reason["method"] == "layout heuristic"
    assert reason["evidence"] == "Test vendor"
    details = get_invoice_details(invoice_pipeline.DB_PATH, result["invoice_id"])
    assert details["invoice"]["enrichment_status"] == "queued"


def test_financial_mismatch_is_retained_and_excluded_from_totals(tmp_path, monkeypatch):
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
