import sqlite3

from backend.database.database import initialize_database, save_extracted_invoice


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
