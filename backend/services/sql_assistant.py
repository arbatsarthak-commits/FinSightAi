import re
import sqlite3
from pathlib import Path

from backend.database.database import db_connection


ALLOWED_TABLES = {"invoices", "invoice_items", "expense_categories"}


def validate_read_only_sql(query: str) -> str:
    cleaned = query.strip().rstrip(";")
    if not re.match(r"^(SELECT|WITH)\b", cleaned, re.IGNORECASE):
        raise ValueError("Only SELECT queries are allowed.")
    forbidden = re.compile(
        r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|ATTACH|DETACH|PRAGMA|VACUUM)\b",
        re.IGNORECASE,
    )
    if forbidden.search(cleaned):
        raise ValueError("The query contains a forbidden database operation.")
    if ";" in cleaned:
        raise ValueError("Multiple SQL statements are not allowed.")
    tables = set(re.findall(r"\b(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_]*)", cleaned, re.I))
    if tables and not tables.issubset(ALLOWED_TABLES):
        raise ValueError("The query references a restricted table.")
    if not re.search(r"\bLIMIT\s+\d+\b", cleaned, re.I):
        cleaned += " LIMIT 200"
    return cleaned


def execute_read_only(db_path: str | Path, query: str) -> list[dict]:
    safe_query = validate_read_only_sql(query)
    with db_connection(db_path) as connection:
        connection.execute("PRAGMA query_only = ON")
        connection.set_authorizer(
            lambda action, arg1, arg2, database, source:
            sqlite3.SQLITE_OK
            if action in {
                sqlite3.SQLITE_SELECT,
                sqlite3.SQLITE_READ,
                sqlite3.SQLITE_FUNCTION,
            } and (
                action != sqlite3.SQLITE_READ
                or arg1 in ALLOWED_TABLES
            )
            else sqlite3.SQLITE_DENY
        )
        cursor = connection.execute(safe_query)
        return [dict(row) for row in cursor.fetchall()]
