import pytest
from backend.services.sql_assistant import validate_read_only_sql


def test_rejects_mutation():
    with pytest.raises(ValueError):
        validate_read_only_sql("DELETE FROM invoices")


def test_rejects_restricted_table():
    with pytest.raises(ValueError):
        validate_read_only_sql("SELECT * FROM sqlite_master")


def test_accepts_limited_select():
    query = validate_read_only_sql("SELECT * FROM invoices")
    assert "LIMIT" in query.upper()
