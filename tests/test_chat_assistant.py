from backend.database.database import initialize_database, save_extracted_invoice
from backend.services.chat_assistant import answer_question


def _insert_invoice(db_path, number, vendor, amount, validation="Verified", category="electronics"):
    return save_extracted_invoice(
        db_path,
        {
            "invoice_number": number,
            "invoice_date": "2026-11-05",
            "vendor_name": vendor,
            "subtotal": amount / 1.18,
            "cgst": amount * 0.09 / 1.18,
            "sgst": amount * 0.09 / 1.18,
            "total_tax": amount * 0.18 / 1.18,
            "grand_total": amount,
            "items": [{"description": "Electronics supply", "amount": amount, "category": category}],
        },
        f"{number}.png",
        {"status": validation},
        "{}",
    )


def test_chat_financial_totals_use_verified_rows_only(tmp_path):
    db_path = tmp_path / "chat.db"
    initialize_database(db_path)
    _insert_invoice(db_path, "INV-1", "ABC Traders", 118)
    _insert_invoice(db_path, "INV-2", "Other Store", 500, validation="Needs Attention")

    answer = answer_question(db_path, "What is my total expenditure?")

    assert answer["intent"] == "spend_total"
    assert answer["rows"][0]["total"] == 118
    assert "₹118.00" in answer["answer"]


def test_chat_followup_uses_previous_vendor_context(tmp_path):
    db_path = tmp_path / "chat-followup.db"
    initialize_database(db_path)
    _insert_invoice(db_path, "INV-1", "ABC Traders", 118)
    _insert_invoice(db_path, "INV-2", "ABC Traders", 236)

    first = answer_question(db_path, "Which vendor has the highest payment?")
    followup = answer_question(
        db_path,
        "Show its invoices",
        [{"role": "assistant", "content": first["answer"], "context": first["context"]}],
    )

    assert first["context"]["vendor"] == "ABC Traders"
    assert followup["intent"] == "vendor_invoices"
    assert len(followup["rows"]) == 2


def test_chat_parameterizes_amount_threshold_and_category_search(tmp_path):
    db_path = tmp_path / "chat-filter.db"
    initialize_database(db_path)
    _insert_invoice(db_path, "INV-1", "ABC Traders", 118)

    threshold = answer_question(db_path, "Show invoices above ₹100")
    category = answer_question(db_path, "How much did I spend on electronics?")

    assert len(threshold["rows"]) == 1
    assert category["rows"][0]["total"] == 118
