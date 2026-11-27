import sqlite3

from backend.database.database import initialize_database, save_extracted_invoice
from backend.services import chat_assistant
from backend.services.chat_assistant import answer_question


def _insert_invoice(
    db_path,
    number,
    vendor,
    amount,
    invoice_date="2026-11-05",
    validation="Verified",
    category="electronics",
):
    subtotal = round(amount / 1.18, 2)
    tax = round(amount - subtotal, 2)
    return save_extracted_invoice(
        db_path,
        {
            "invoice_number": number,
            "invoice_date": invoice_date,
            "vendor_name": vendor,
            "subtotal": subtotal,
            "cgst": round(tax / 2, 2),
            "sgst": round(tax / 2, 2),
            "igst": 0,
            "total_tax": tax,
            "grand_total": amount,
            "items": [{
                "description": "Electronics supply",
                "amount": subtotal,
                "taxable_value": subtotal,
                "category": category,
            }],
        },
        f"{number}.png",
        {"status": validation},
        "{}",
    )


def _seed(db_path):
    initialize_database(db_path)
    first = _insert_invoice(db_path, "INV-1", "ABC Traders", 118, "2026-11-05")
    second = _insert_invoice(db_path, "INV-2", "ABC Traders", 236, "2026-10-05")
    _insert_invoice(db_path, "INV-3", "Other Store", 500, validation="Needs Attention")
    return first, second


def test_chat_financial_totals_use_verified_rows_and_show_support(tmp_path):
    db_path = tmp_path / "chat.db"
    first, second = _seed(db_path)

    answer = answer_question(db_path, "What is my total expenditure?")

    assert answer["intent"] == "spend_total"
    assert answer["calculation"]["total"] == 354
    assert {row["id"] for row in answer["supporting_invoices"]} == {first, second}
    assert answer["calculation"]["provisional_summary"]["total"] == 500
    assert answer["provisional_invoices"][0]["validation_status"] == "Needs Attention"
    assert "₹354.00" in answer["answer"]
    assert "excluded from verified spend" in answer["answer"]


def test_chat_total_explains_unpriced_provisional_invoices(tmp_path):
    db_path = tmp_path / "chat-unpriced-provisional.db"
    initialize_database(db_path)
    save_extracted_invoice(
        db_path,
        {
            "invoice_number": "INV-UNPRICED",
            "invoice_date": "2026-11-05",
            "vendor_name": "Example Vendor",
            "grand_total": None,
        },
        "unpriced.png",
        {"status": "Needs Attention"},
        "{}",
    )

    answer = answer_question(db_path, "What is my total expenditure?")

    assert answer["calculation"]["total"] is None
    assert answer["calculation"]["provisional_summary"]["missing_total_count"] == 1
    assert answer["provisional_invoices"][0]["grand_total"] is None
    assert "no verified invoice totals" in answer["answer"].lower()
    assert "no recorded totals" in answer["answer"]


def test_chat_followup_uses_previous_vendor_context(tmp_path):
    db_path = tmp_path / "chat-followup.db"
    first, second = _seed(db_path)

    first_answer = answer_question(db_path, "Which vendor has the highest payment?")
    followup = answer_question(
        db_path,
        "Show its invoices",
        [{"role": "assistant", "content": first_answer["answer"], "context": first_answer["context"]}],
    )

    assert first_answer["context"]["vendor"] == "ABC Traders"
    assert followup["intent"] == "vendor_invoices"
    assert {row["id"] for row in followup["rows"]} == {first, second}


def test_chat_followup_retrieves_line_items_for_previous_invoice(tmp_path):
    db_path = tmp_path / "chat-invoice-followup.db"
    first, _ = _seed(db_path)

    first_answer = answer_question(db_path, "Show details for invoice number INV-1")
    followup = answer_question(
        db_path,
        "What are its line items?",
        [{"role": "assistant", "content": first_answer["answer"], "context": first_answer["context"]}],
    )

    assert followup["intent"] == "invoice_detail"
    assert {row["id"] for row in followup["supporting_invoices"]} == {first}
    assert followup["calculation"]["line_items"][0]["description"] == "Electronics supply"


def test_chat_followup_uses_saved_invoice_id_when_invoice_number_is_missing(tmp_path):
    db_path = tmp_path / "chat-no-invoice-number.db"
    invoice_id = _insert_invoice(db_path, None, "Example Vendor", 118)

    first_answer = answer_question(db_path, "Show latest uploaded invoice")
    followup = answer_question(
        db_path,
        "What are its line items?",
        [{"role": "assistant", "content": first_answer["answer"], "context": first_answer["context"]}],
    )

    assert first_answer["context"]["invoice_id"] == invoice_id
    assert followup["intent"] == "invoice_detail"
    assert followup["supporting_invoices"][0]["id"] == invoice_id


def test_monthly_yearly_and_month_comparison_queries_use_database_dates(tmp_path):
    db_path = tmp_path / "chat-periods.db"
    _seed(db_path)

    monthly = answer_question(db_path, "What is my monthly expenditure in 2026?")
    yearly = answer_question(db_path, "What was my yearly expenditure in 2026?")
    comparison = answer_question(
        db_path, "Compare November 2026 with October 2026 expenditure"
    )

    assert monthly["intent"] == "spend_monthly"
    assert len(monthly["calculation"]["months"]) == 2
    assert monthly["calculation"]["provisional_summary"]["total"] == 500
    assert monthly["provisional_invoices"][0]["validation_status"] == "Needs Attention"
    assert yearly["calculation"]["total"] == 354
    assert comparison["intent"] == "month_comparison"
    assert len(comparison["supporting_invoices"]) == 2
    assert comparison["calculation"]["provisional_months"][0]["amount"] == 500
    assert comparison["provisional_invoices"][0]["validation_status"] == "Needs Attention"


def test_gst_breakdown_and_category_queries_are_supported(tmp_path):
    db_path = tmp_path / "chat-gst.db"
    _seed(db_path)

    taxes = answer_question(db_path, "Show my GST breakdown")
    categories = answer_question(db_path, "Show my top five expense categories")
    category_spend = answer_question(db_path, "How much did I spend on electronics?")

    assert taxes["intent"] == "gst_breakdown"
    assert taxes["calculation"]["cgst"] > 0
    assert len(taxes["supporting_invoices"]) == 2
    assert taxes["calculation"]["provisional_summary"]["cgst"] > 0
    assert taxes["provisional_invoices"][0]["validation_status"] == "Needs Attention"
    assert categories["intent"] == "category_top"
    assert categories["calculation"]["categories"][0]["category"] == "electronics"
    assert categories["calculation"]["provisional_categories"][0]["category"] == "electronics"
    assert category_spend["calculation"]["invoice_count"] == 2
    assert category_spend["calculation"]["provisional_summary"]["invoice_count"] == 1
    assert category_spend["provisional_invoices"][0]["validation_status"] == "Needs Attention"


def test_chat_does_not_report_missing_tax_as_zero(tmp_path):
    db_path = tmp_path / "chat-missing-tax.db"
    initialize_database(db_path)
    save_extracted_invoice(
        db_path,
        {
            "invoice_number": "INV-NO-TAX",
            "invoice_date": "2026-11-05",
            "vendor_name": "Example Vendor",
            "grand_total": 100,
            "items": [{
                "description": "Unpriced electronics item",
                "category": "electronics",
            }],
        },
        "no-tax.png",
        {"status": "Verified"},
        "{}",
    )

    total = answer_question(db_path, "How much tax did I pay?")
    breakdown = answer_question(db_path, "Show my GST breakdown")
    category = answer_question(db_path, "How much did I spend on electronics?")

    assert total["calculation"]["tax_total"] is None
    assert total["calculation"]["missing_tax_count"] == 1
    assert "no verified invoices have recorded tax amounts" in total["answer"].lower()
    assert breakdown["calculation"]["cgst"] is None
    assert "not recorded" in breakdown["answer"]
    assert category["calculation"]["total"] is None
    assert "no recorded amounts" in category["answer"]


def test_vendor_frequency_invoice_lookup_and_product_search(tmp_path):
    db_path = tmp_path / "chat-search.db"
    first, second = _seed(db_path)

    frequent = answer_question(db_path, "Which vendor is most frequently purchased from?")
    invoice = answer_question(db_path, "Show details for invoice number INV-1")
    products = answer_question(db_path, "Find products containing electronics")

    assert frequent["intent"] == "vendor_frequency"
    assert frequent["context"]["vendor"] == "ABC Traders"
    assert frequent["calculation"]["provisional_vendor"]["vendor"] == "Other Store"
    assert invoice["intent"] == "invoice_detail"
    assert invoice["context"]["invoice_number"] == "INV-1"
    assert invoice["calculation"]["line_items"][0]["description"] == "Electronics supply"
    assert {row["id"] for row in products["rows"]} == {first, second, 3}
    assert any(row["validation_status"] == "Needs Attention" for row in products["rows"])


def test_threshold_queries_and_absent_data_are_explicit(tmp_path, monkeypatch):
    db_path = tmp_path / "chat-threshold.db"
    _seed(db_path)
    monkeypatch.setattr(chat_assistant, "_model_intent", lambda question, history: {"intent": "unknown"})

    above = answer_question(db_path, "Show invoices above ₹200")
    below = answer_question(db_path, "Show invoices below ₹200")
    unknown = answer_question(db_path, "Tell me about my cryptocurrency portfolio")

    assert above["calculation"]["count"] == 2
    assert below["calculation"]["count"] == 1
    assert unknown["intent"] == "unknown"
    assert "couldn't map" in unknown["answer"]
    assert "₹" not in unknown["answer"]


def test_chat_stage_timings_are_persisted(tmp_path):
    db_path = tmp_path / "chat-metrics.db"
    _seed(db_path)

    response = answer_question(db_path, "What is my total expenditure?")

    assert set(response["performance"]) == {
        "intent_detection_seconds", "sql_execution_seconds", "response_generation_seconds"
    }
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            "SELECT stage, duration_seconds FROM performance_metrics WHERE request_id IS NOT NULL"
        ).fetchall()
    assert {row[0] for row in rows} == set(response["performance"])
    assert all(value >= 0 for _, value in rows)
