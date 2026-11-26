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
