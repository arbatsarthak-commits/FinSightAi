import sqlite3
from contextlib import contextmanager
from pathlib import Path
import json


SCHEMA = """
CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_number TEXT,
    invoice_date TEXT,
    due_date TEXT,
    vendor_name TEXT,
    vendor_gstin TEXT,
    customer_name TEXT,
    customer_gstin TEXT,
    subtotal REAL,
    cgst REAL,
    sgst REAL,
    igst REAL,
    total_tax REAL,
    grand_total REAL,
    currency TEXT DEFAULT 'INR',
    payment_status TEXT,
    source_file TEXT,
    source_hash TEXT,
    extraction_status TEXT DEFAULT 'Extracted',
    validation_status TEXT DEFAULT 'Needs Review',
    approval_status TEXT DEFAULT 'Automatic',
    processing_status TEXT DEFAULT 'Needs Attention',
    extracted_data TEXT,
    corrected_data TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_invoices_number ON invoices(invoice_number);
CREATE INDEX IF NOT EXISTS idx_invoices_number_normalized ON invoices(lower(trim(invoice_number)));
CREATE INDEX IF NOT EXISTS idx_invoices_vendor ON invoices(vendor_name);
CREATE INDEX IF NOT EXISTS idx_invoices_date ON invoices(invoice_date);
CREATE INDEX IF NOT EXISTS idx_invoices_validation ON invoices(validation_status);
CREATE UNIQUE INDEX IF NOT EXISTS ux_invoices_source_hash ON invoices(source_hash);

CREATE TABLE IF NOT EXISTS invoice_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER NOT NULL,
    description TEXT,
    quantity REAL,
    unit_price REAL,
    discount REAL,
    discount_percent REAL,
    taxable_value REAL,
    cgst REAL,
    sgst REAL,
    igst REAL,
    amount REAL,
    category TEXT,
    FOREIGN KEY(invoice_id) REFERENCES invoices(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_invoice_items_invoice ON invoice_items(invoice_id);
CREATE INDEX IF NOT EXISTS idx_invoice_items_category ON invoice_items(category);

CREATE TABLE IF NOT EXISTS expense_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_expense_categories_name ON expense_categories(name);

CREATE TABLE IF NOT EXISTS processing_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER,
    stage TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(invoice_id) REFERENCES invoices(id) ON DELETE SET NULL
);
"""


def initialize_database(db_path: str | Path) -> None:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='invoices'"
        ).fetchone()
        if table:
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(invoices)").fetchall()
            }
            if "source_hash" not in columns:
                connection.execute("ALTER TABLE invoices ADD COLUMN source_hash TEXT")
            if "processing_status" not in columns:
                connection.execute(
                    "ALTER TABLE invoices ADD COLUMN processing_status TEXT DEFAULT 'Needs Attention'"
                )
                connection.execute(
                    """UPDATE invoices
                       SET processing_status = CASE
                           WHEN validation_status = 'Verified' THEN 'Processed'
                           ELSE 'Needs Attention'
                       END"""
                )
        item_table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='invoice_items'"
        ).fetchone()
        if item_table:
            item_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(invoice_items)").fetchall()
            }
            if "discount_percent" not in item_columns:
                connection.execute(
                    "ALTER TABLE invoice_items ADD COLUMN discount_percent REAL"
                )
        connection.executescript(SCHEMA)
        connection.execute(
            "INSERT OR IGNORE INTO expense_categories(name) VALUES "
            "('food'),('logistics'),('drinks'),('travel'),"
            "('grocery expense'),('utilities'),('Other')"
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


@contextmanager
def db_connection(db_path: str | Path):
    initialize_database(db_path)
    connection = sqlite3.connect(db_path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def save_extracted_invoice(db_path: str | Path, invoice: dict, source_file: str,
                           validation: dict, extracted_json: str,
                           processing_status: str | None = None,
                           source_hash: str | None = None) -> int:
    if processing_status is None:
        processing_status = (
            "Processed" if validation.get("status") == "Verified" else "Needs Attention"
        )
    with db_connection(db_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO invoices (
                invoice_number, invoice_date, due_date, vendor_name, vendor_gstin,
                customer_name, customer_gstin, subtotal, cgst, sgst, igst, total_tax,
                grand_total, currency, payment_status, source_file, source_hash, extraction_status,
                validation_status, approval_status, processing_status, extracted_data, corrected_data
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Extracted',
                ?, 'Automatic', ?, ?, ?)
            """,
            (
                invoice.get("invoice_number"), invoice.get("invoice_date"), invoice.get("due_date"),
                invoice.get("vendor_name"), invoice.get("vendor_gstin"),
                invoice.get("customer_name"), invoice.get("customer_gstin"),
                invoice.get("subtotal"), invoice.get("cgst"), invoice.get("sgst"),
                invoice.get("igst"), invoice.get("total_tax"), invoice.get("grand_total"),
                invoice.get("currency", "INR"), invoice.get("payment_status"), source_file, source_hash,
                validation["status"], processing_status, extracted_json,
                json.dumps(invoice, ensure_ascii=False),
            ),
        )
        invoice_id = cursor.lastrowid
        for item in invoice.get("items", []):
            connection.execute(
                """
                INSERT INTO invoice_items (
                    invoice_id, description, quantity, unit_price, discount, discount_percent,
                    taxable_value, cgst, sgst, igst, amount, category
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    invoice_id, item.get("description"), item.get("quantity"),
                    item.get("unit_price"), item.get("discount"), item.get("discount_percent"),
                    item.get("taxable_value"),
                    item.get("cgst"), item.get("sgst"), item.get("igst"),
                    item.get("amount"), item.get("category", "Other"),
                ),
            )
        connection.execute(
            "INSERT INTO processing_logs(invoice_id, stage, status, message) VALUES (?, 'save', 'success', '')",
            (invoice_id,),
        )
        return invoice_id


def get_dashboard_data(db_path: str | Path) -> dict:
    with db_connection(db_path) as connection:
        summary = connection.execute(
            """
            SELECT COALESCE(SUM(CASE WHEN validation_status = 'Verified' THEN grand_total ELSE 0 END), 0) AS total_expenses,
                   COALESCE(SUM(CASE WHEN validation_status = 'Verified' THEN 1 ELSE 0 END), 0) AS total_invoices,
                   COALESCE(SUM(CASE WHEN validation_status = 'Verified' THEN total_tax ELSE 0 END), 0) AS total_tax,
                   COALESCE(AVG(CASE WHEN validation_status = 'Verified' THEN grand_total END), 0) AS average_invoice,
                   COALESCE(SUM(CASE WHEN validation_status != 'Verified' OR validation_status IS NULL THEN 1 ELSE 0 END), 0) AS needs_attention
            FROM invoices
            """
        ).fetchone()
        categories = connection.execute(
            """
            SELECT COALESCE(category, 'Other') AS category, COALESCE(SUM(amount), 0) AS amount
            FROM invoice_items i
            JOIN invoices n ON n.id = i.invoice_id
            WHERE n.validation_status = 'Verified'
            GROUP BY COALESCE(category, 'Other') ORDER BY amount DESC
            """
        ).fetchall()
        vendors = connection.execute(
            """
            SELECT COALESCE(vendor_name, 'Unknown') AS vendor,
                   COALESCE(SUM(grand_total), 0) AS amount
            FROM invoices
            WHERE validation_status = 'Verified'
            GROUP BY COALESCE(vendor_name, 'Unknown') ORDER BY amount DESC LIMIT 10
            """
        ).fetchall()
        monthly = connection.execute(
            """
            SELECT substr(invoice_date, 1, 7) AS month, COALESCE(SUM(grand_total), 0) AS amount
            FROM invoices
            WHERE invoice_date IS NOT NULL AND validation_status = 'Verified'
            GROUP BY substr(invoice_date, 1, 7) ORDER BY month
            """
        ).fetchall()
        recent = connection.execute(
            """
            SELECT id, invoice_number, invoice_date, vendor_name, grand_total,
                   validation_status, processing_status
            FROM invoices ORDER BY id DESC LIMIT 10
            """
        ).fetchall()
        return {
            "summary": dict(summary),
            "categories": [dict(row) for row in categories],
            "vendors": [dict(row) for row in vendors],
            "monthly": [dict(row) for row in monthly],
            "recent": [dict(row) for row in recent],
        }


def get_invoice_details(db_path: str | Path, invoice_id: int) -> dict:
    with db_connection(db_path) as connection:
        invoice = connection.execute(
            "SELECT * FROM invoices WHERE id = ?", (invoice_id,)
        ).fetchone()
        if invoice is None:
            return {}
        items = connection.execute(
            "SELECT * FROM invoice_items WHERE invoice_id = ? ORDER BY id",
            (invoice_id,),
        ).fetchall()
        logs = connection.execute(
            "SELECT * FROM processing_logs WHERE invoice_id = ? ORDER BY id",
            (invoice_id,),
        ).fetchall()
        return {
            "invoice": dict(invoice),
            "items": [dict(row) for row in items],
            "logs": [dict(row) for row in logs],
        }
