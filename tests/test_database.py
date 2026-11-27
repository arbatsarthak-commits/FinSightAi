import sqlite3

from backend.database.database import (
    get_dashboard_data,
    get_invoice_details,
    initialize_database,
    record_performance_metrics,
    save_extracted_invoice,
)


def test_database_save_and_foreign_key(tmp_path):
    db_path = tmp_path / "test.db"
    initialize_database(db_path)
    invoice = {
        "invoice_number": "INV-1",
        "invoice_date": "2026-11-22",
        "vendor_name": "Example",
        "subtotal": 100,
        "grand_total": 100,
        "items": [{"description": "Service", "amount": 100, "category": "Other"}],
    }
    invoice_id = save_extracted_invoice(
        db_path, invoice, "test.png", {"status": "Verified"}, "{}",
        source_hash="abc123",
    )
    assert invoice_id == 1
    with sqlite3.connect(db_path) as connection:
        corrected_data = connection.execute(
            "SELECT corrected_data FROM invoices WHERE id=?", (invoice_id,)
        ).fetchone()[0]
    assert corrected_data is None


def test_legacy_invoice_rows_survive_processing_status_migration(tmp_path):
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """CREATE TABLE invoices (
                id INTEGER PRIMARY KEY,
                invoice_number TEXT,
                invoice_date TEXT,
                vendor_name TEXT,
                grand_total REAL,
                total_tax REAL,
                source_file TEXT,
                validation_status TEXT,
                approval_status TEXT
            )"""
        )
        connection.execute(
            """CREATE TABLE invoice_items (
                id INTEGER PRIMARY KEY,
                invoice_id INTEGER NOT NULL,
                description TEXT,
                quantity REAL,
                unit_price REAL,
                discount REAL,
                taxable_value REAL,
                cgst REAL,
                sgst REAL,
                igst REAL,
                amount REAL,
                category TEXT
            )"""
        )
        connection.execute(
            """INSERT INTO invoices
               (id, invoice_number, invoice_date, vendor_name, grand_total, total_tax,
                source_file, validation_status, approval_status)
               VALUES (7, 'INV-OLD', '2026-11-22', 'Old vendor', 118, 18,
                       'old.png', 'Verified', 'Pending')"""
        )
        connection.execute(
            """INSERT INTO invoice_items
               (id, invoice_id, description, quantity, unit_price, discount, amount)
               VALUES (12, 7, 'Old item', 1, 100, 0, 100)"""
        )

    initialize_database(db_path)

    with sqlite3.connect(db_path) as connection:
        invoice = connection.execute(
            """SELECT id, invoice_number, grand_total, approval_status, processing_status
               FROM invoices WHERE id = 7"""
        ).fetchone()
        item = connection.execute(
            """SELECT id, description, amount, discount_percent
               FROM invoice_items WHERE id = 12"""
        ).fetchone()
    assert invoice == (7, "INV-OLD", 118.0, "Pending", "Processed")
    assert item == (12, "Old item", 100.0, None)


def test_evidence_and_metrics_are_persisted_with_query_indexes(tmp_path):
    db_path = tmp_path / "evidence.db"
    initialize_database(db_path)
    evidence = {
        "invoice_number": {
            "source": "tesseract",
            "line": "Invoice No INV-3",
            "confidence": 0.96,
        },
        "items": [{
            "item": 1,
            "fields": {"description": {"source": "tesseract", "line": "Tea"}},
            "confidence": 0.94,
        }],
    }
    invoice_id = save_extracted_invoice(
        db_path,
        {
            "invoice_number": "INV-3",
            "vendor_name": "Tea Supplier",
            "invoice_date": "2026-11-22",
            "grand_total": 118,
            "items": [{"description": "Tea", "amount": 100, "category": "food"}],
        },
        "invoice.png",
        {"status": "Needs Attention"},
        "{}",
        ocr_text="Invoice No INV-3",
        ocr_words=[{"text": "INV-3", "left": 120, "top": 30}],
        field_evidence=evidence,
        field_confidence={"invoice_number": 0.96},
        item_evidence=evidence["items"],
        enrichment_status="queued",
    )
    record_performance_metrics(
        db_path,
        [{"stage": "ocr", "duration_seconds": 0.25, "status": "complete"}],
        invoice_id=invoice_id,
        request_id="sample",
    )

    details = get_invoice_details(db_path, invoice_id)
    with sqlite3.connect(db_path) as connection:
        invoice_indexes = {
            row[1] for row in connection.execute("PRAGMA index_list(invoices)")
        }
        item_indexes = {
            row[1] for row in connection.execute("PRAGMA index_list(invoice_items)")
        }
        metric = connection.execute(
            "SELECT stage, duration_seconds FROM performance_metrics WHERE request_id='sample'"
        ).fetchone()

    assert details["invoice"]["ocr_text"] == "Invoice No INV-3"
    assert details["invoice"]["field_evidence"] == evidence
    assert details["invoice"]["field_confidence"] == {"invoice_number": 0.96}
    assert details["invoice"]["enrichment_status"] == "queued"
    assert details["items"][0]["evidence"]["confidence"] == 0.94
    assert "idx_invoices_vendor_normalized" in invoice_indexes
    assert "idx_invoices_date" in invoice_indexes
    assert "idx_invoices_validation" in invoice_indexes
    assert "idx_invoice_items_category_normalized" in item_indexes
    assert "idx_invoice_items_description" in item_indexes
    assert metric == ("ocr", 0.25)


def test_dashboard_separates_verified_and_provisional_aggregates(tmp_path):
    db_path = tmp_path / "dashboard.db"
    initialize_database(db_path)
    for number, status, amount in (
        ("INV-VERIFIED", "Verified", 118),
        ("INV-PROVISIONAL", "Needs Attention", 236),
    ):
        save_extracted_invoice(
            db_path,
            {
                "invoice_number": number,
                "invoice_date": "2026-11-22",
                "vendor_name": "Example",
                "subtotal": amount - 18,
                "total_tax": 18,
                "grand_total": amount,
                "items": [{
                    "description": "Service",
                    "amount": amount - 18,
                    "taxable_value": amount - 18,
                    "category": "services",
                }],
            },
            f"{number}.png",
            {"status": status},
            "{}",
        )

    dashboard = get_dashboard_data(db_path)

    assert dashboard["summary"]["total_expenses"] == 118
    assert dashboard["summary"]["total_invoices"] == 1
    assert dashboard["summary"]["invoice_count"] == 2
    assert dashboard["provisional_summary"]["total_expenses"] == 236
    assert dashboard["provisional_summary"]["invoice_count"] == 1
    assert dashboard["provisional_summary"]["tax_record_count"] == 1
    assert dashboard["provisional_vendors"][0]["amount"] == 236
    assert dashboard["provisional_monthly"][0]["amount"] == 236
    assert dashboard["provisional_categories"][0]["amount"] == 218
