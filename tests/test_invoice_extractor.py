from backend.services.invoice_extractor import extract_invoice_from_ocr


def _word(text, left, top, line_num, confidence=94):
    return {
        "text": text,
        "confidence": confidence,
        "left": left,
        "top": top,
        "width": max(8, len(text) * 8),
        "height": 18,
        "block_num": 1,
        "par_num": 1,
        "line_num": line_num,
        "page": 1,
    }


def _line(text, top, line_num, positions=None):
    tokens = text.split()
    if positions is None:
        positions = [10 + index * 75 for index in range(len(tokens))]
    return [
        _word(token, positions[index], top, line_num)
        for index, token in enumerate(tokens)
    ]


def _invoice_ocr():
    rows = [
        _line("ACME FOODS PRIVATE LIMITED", 20, 1),
        _line("Invoice No: INV-2025/001", 50, 2),
        _line("Invoice Date: 12/04/2025", 80, 3),
        _line("GSTIN: 27ABCDE1234F1Z5", 110, 4),
        _line(
            "Description Qty Rate Taxable Value",
            200,
            5,
            [10, 300, 400, 500, 570],
        ),
        _line("Widget 2 500.00 1,000.00", 230, 6, [10, 300, 400, 500]),
        _line("Subtotal: 1,000.00", 330, 7),
        _line("CGST: 90.00", 360, 8),
        _line("SGST: 90.00", 390, 9),
        _line("Grand Total: 1,180.00", 420, 10),
    ]
    words = [word for line in rows for word in line]
    return {
        "text": "\n".join(" ".join(word["text"] for word in line) for line in rows),
        "words": words,
    }


def test_extracts_indian_invoice_fields_with_evidence_and_coordinates():
    result = extract_invoice_from_ocr(_invoice_ocr())
    invoice = result["invoice"]

    assert invoice["invoice_number"] == "INV-2025/001"
    assert invoice["invoice_date"] == "2025-04-12"
    assert invoice["vendor_gstin"] == "27ABCDE1234F1Z5"
    assert invoice["subtotal"] == 1000
    assert invoice["cgst"] == 90
    assert invoice["sgst"] == 90
    assert invoice["grand_total"] == 1180
    assert invoice["items"][0]["description"] == "Widget"
    assert invoice["items"][0]["quantity"] == 2
    assert invoice["items"][0]["unit_price"] == 500
    assert invoice["items"][0]["taxable_value"] == 1000
    assert result["confidence"]["grand_total"] > 0.9
    assert result["evidence"]["grand_total"]["page"] == 1
    assert result["evidence"]["grand_total"]["bbox"]["top"] == 420
    assert result["evidence"]["items"][0]["fields"]["quantity"]["bbox"]["left"] == 300


def test_missing_values_are_not_filled_and_keep_missing_evidence():
    result = extract_invoice_from_ocr(
        {"text": "Tax Invoice\nDescription Qty Amount\nSoap 1 25.00", "words": []}
    )

    assert result["invoice"]["grand_total"] is None
    assert result["invoice"]["vendor_name"] is None
    assert result["invoice"]["items"] == []
    assert result["confidence"]["grand_total"] == 0
    assert result["evidence"]["grand_total"]["source"] == "missing"


def test_tax_rate_percentages_are_not_mistaken_for_tax_amounts():
    result = extract_invoice_from_ocr({
        "text": "Date: 12/04/2025\nCGST 9%\nSGST 9%",
        "words": [],
    })

    assert result["invoice"]["invoice_date"] == "2025-04-12"
    assert result["invoice"]["cgst"] is None
    assert result["invoice"]["sgst"] is None


def test_extracts_receipt_bill_number_total_and_wrapped_items_across_pages():
    first_page = [
        _line("LA PATISSERIE AFFAIRE", 20, 1),
        _line("GSTIN: 27AASFT7992A1ZK", 50, 2),
        _line("Bill: S-4853 / Order No: S3", 80, 3),
        _line("Date: 10-11-2026 11:50 AM", 110, 4),
        _line("Tten Oty Rate Ant", 150, 5, [10, 300, 400, 500]),
        _line("Chocolate 1 399.00 399.00", 180, 6, [10, 300, 400, 500]),
        _line("Bento Cake", 205, 7, [10, 85]),
        _line("Item Subtotal 549.00", 250, 8),
        _line("SGST 2.5% 13.55", 280, 9),
        _line("CGST 2.5% 13.55", 310, 10),
        _line("TOTAL 569.00", 340, 11),
    ]
    second_page = [
        _line("Tten Oty Rate Ant", 20, 1, [10, 300, 400, 500]),
        _line("Coffee 1 150.00 150.00", 50, 2, [10, 300, 400, 500]),
    ]
    for word in (word for line in second_page for word in line):
        word["page"] = 2
    words = [word for line in first_page for word in line]
    words.extend(word for line in second_page for word in line)
    ocr = {
        "text": "\n".join(
            " ".join(word["text"] for word in line)
            for line in first_page + second_page
        ),
        "words": words,
    }

    result = extract_invoice_from_ocr(ocr)
    invoice = result["invoice"]

    assert invoice["vendor_name"] == "LA PATISSERIE AFFAIRE"
    assert invoice["invoice_number"] == "S-4853"
    assert invoice["invoice_date"] == "2026-11-10"
    assert invoice["grand_total"] == 569
    assert invoice["cgst"] == 13.55
    assert invoice["sgst"] == 13.55
    assert [item["description"] for item in invoice["items"]] == [
        "Chocolate Bento Cake",
        "Coffee",
    ]
    assert [item["amount"] for item in invoice["items"]] == [399, 150]
    assert result["evidence"]["items"][1]["fields"]["description"]["page"] == 2
