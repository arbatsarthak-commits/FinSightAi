from backend.validation.validation_engine import validate_invoice
from backend.models.invoice import InvoiceData


def test_subtotal_and_item_mismatch_is_reported():
    invoice = {
        "invoice_number": "INV-1",
        "invoice_date": "2026-11-22",
        "vendor_name": "Example",
        "subtotal": 100,
        "grand_total": 118,
        "items": [{
            "description": "Item", "quantity": 1, "unit_price": 100,
            "taxable_value": 90, "amount": 90,
        }],
        "cgst": 9,
        "sgst": 9,
        "igst": 0,
        "total_tax": 18,
    }
    result = validate_invoice(invoice)
    assert result["status"] == "Validation Failed"
    assert any("quantity x unit price" in error for error in result["errors"])


def test_tax_inclusive_item_amount_is_not_compared_as_taxable_subtotal():
    invoice = {
        "invoice_number": "INV-TAX-INCLUSIVE",
        "invoice_date": "2026-11-22",
        "vendor_name": "Example",
        "subtotal": 100,
        "cgst": 9,
        "sgst": 9,
        "igst": 0,
        "total_tax": 18,
        "grand_total": 118,
        "items": [{
            "description": "Tax-inclusive item",
            "quantity": 1,
            "unit_price": 118,
            "amount": 118,
        }],
    }

    result = validate_invoice(invoice)

    assert result["status"] == "Verified"


def test_item_amounts_reconcile_to_subtotal_when_invoice_has_summary_tax():
    invoice = {
        "invoice_number": "INV-LINE-TAX",
        "invoice_date": "2026-11-22",
        "vendor_name": "Example",
        "subtotal": 549,
        "cgst": 13.55,
        "sgst": 13.55,
        "igst": 0,
        "total_tax": 27.1,
        "grand_total": 576.1,
        "items": [
            {"description": "First", "quantity": 1, "unit_price": 399, "amount": 399},
            {"description": "Second", "quantity": 1, "unit_price": 150, "amount": 150},
        ],
    }

    result = validate_invoice(invoice)

    assert result["status"] == "Verified"


def test_item_amounts_mismatching_subtotal_and_grand_total_fail_reconciliation():
    invoice = {
        "invoice_number": "INV-LINE-MISMATCH",
        "invoice_date": "2026-11-22",
        "vendor_name": "Example",
        "subtotal": 549,
        "cgst": 13.55,
        "sgst": 13.55,
        "igst": 0,
        "total_tax": 27.1,
        "grand_total": 576.1,
        "items": [{"description": "First", "amount": 500}],
    }

    result = validate_invoice(invoice)

    assert result["status"] == "Validation Failed"
    assert any("line-item amounts" in error for error in result["errors"])


def test_missing_gst_components_are_not_assumed_to_be_zero():
    result = validate_invoice({
        "invoice_number": "INV-MISSING-GST",
        "invoice_date": "2026-11-22",
        "vendor_name": "Example",
        "subtotal": 100,
        "total_tax": 18,
        "grand_total": 118,
    })

    assert result["status"] == "Needs Attention"
    assert any("Tax components are missing" in warning for warning in result["warnings"])
    assert not any("CGST + SGST + IGST" in error for error in result["errors"])


def test_partial_gst_components_are_not_reconciled_as_complete():
    result = validate_invoice({
        "invoice_number": "INV-PARTIAL-GST",
        "invoice_date": "2026-11-22",
        "vendor_name": "Example",
        "subtotal": 100,
        "cgst": 9,
        "total_tax": 9,
        "grand_total": 109,
    })

    assert result["status"] == "Needs Attention"
    assert any("breakdown is incomplete" in warning for warning in result["warnings"])
    assert not any("CGST + SGST + IGST" in error for error in result["errors"])


def test_recorded_round_off_reconciles_grand_total():
    invoice = {
        "invoice_number": "INV-ROUND-OFF",
        "invoice_date": "2026-11-22",
        "vendor_name": "Example",
        "subtotal": 100,
        "cgst": 9,
        "sgst": 9,
        "igst": 0,
        "total_tax": 18,
        "round_off": -0.01,
        "grand_total": 117.99,
    }

    assert validate_invoice(invoice)["status"] == "Verified"


def test_small_unrecorded_round_off_requires_attention_not_failure():
    result = validate_invoice({
        "invoice_number": "INV-UNRECORDED-ROUND-OFF",
        "invoice_date": "2026-11-22",
        "vendor_name": "Example",
        "subtotal": 100,
        "cgst": 9,
        "sgst": 9,
        "igst": 0,
        "total_tax": 18,
        "grand_total": 117.99,
    })

    assert result["status"] == "Needs Attention"
    assert not result["errors"]
    assert any("round-off value was not extracted" in warning for warning in result["warnings"])


def test_fractional_quantity_is_not_rounded_as_currency():
    result = validate_invoice({
        "invoice_number": "INV-FRACTIONAL-QUANTITY",
        "invoice_date": "2026-11-22",
        "vendor_name": "Example",
        "subtotal": 10,
        "cgst": 0,
        "sgst": 0,
        "igst": 0,
        "total_tax": 0,
        "grand_total": 10,
        "tax_inclusive": True,
        "items": [{
            "description": "Fractional item",
            "quantity": 0.125,
            "unit_price": 80,
            "amount": 10,
            "amount_basis": "taxable",
        }],
    })

    assert result["status"] == "Verified"


def test_missing_subtotal_and_line_items_needs_attention():
    result = validate_invoice({
        "invoice_number": "INV-INCOMPLETE",
        "invoice_date": "2026-11-22",
        "vendor_name": "Example",
        "grand_total": 118,
    })

    assert result["status"] == "Needs Attention"
    assert any("financial totals could not be reconciled" in warning for warning in result["warnings"])


def test_percentage_discount_is_parsed_and_used_in_validation():
    invoice = InvoiceData.model_validate({
        "invoice_number": "INV-DISCOUNT",
        "invoice_date": "2026-11-22",
        "vendor_name": "Example",
        "subtotal": 380,
        "grand_total": 380,
        "items": [{
            "description": "Discounted item",
            "quantity": 4,
            "unit_price": 100,
            "discount": "5%",
            "taxable_value": 380,
            "amount": 380,
        }],
    })

    assert invoice.items[0].discount is None
    assert invoice.items[0].discount_percent == 5
    assert validate_invoice(invoice.model_dump())["status"] == "Verified"

    percent_field_invoice = InvoiceData.model_validate({
        "items": [{"discount_percent": "5%"}],
    })
    assert percent_field_invoice.items[0].discount_percent == 5
