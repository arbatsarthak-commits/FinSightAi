from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Iterable


MONEY = Decimal("0.01")


def money(value) -> Decimal:
    if value is None:
        return Decimal("0")
    try:
        return Decimal(str(value)).quantize(MONEY, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return Decimal("0")


def valid_date(value: str | None) -> bool:
    if not value:
        return False
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            datetime.strptime(value, fmt)
            return True
        except ValueError:
            continue
    return False


def validate_invoice(invoice: dict, existing_invoice_numbers: Iterable[str] = ()) -> dict:
    warnings = []
    errors = []
    missing = []

    for field in ("invoice_number", "invoice_date", "vendor_name", "grand_total"):
        if not invoice.get(field):
            missing.append(field)

    if invoice.get("invoice_date") and not valid_date(invoice["invoice_date"]):
        warnings.append("Invoice date is invalid or ambiguous.")
    if invoice.get("due_date") and not valid_date(invoice["due_date"]):
        warnings.append("Due date is invalid or ambiguous.")

    number = invoice.get("invoice_number")
    existing_numbers = {str(value).strip().lower() for value in existing_invoice_numbers}
    if number and str(number).strip().lower() in existing_numbers:
        warnings.append("A confirmed invoice with this invoice number already exists.")

    items = invoice.get("items") or []
    if not items and invoice.get("subtotal") is None:
        warnings.append("Subtotal or line items are missing; financial totals could not be reconciled.")
    item_sum = Decimal("0")
    item_sum_comparable = True
    for index, item in enumerate(items, start=1):
        quantity = item.get("quantity")
        unit_price = item.get("unit_price")
        amount = item.get("amount")
        taxable_value = item.get("taxable_value")
        item_tax = any(money(item.get(field)) != 0 for field in ("cgst", "sgst", "igst"))
        if quantity is not None and unit_price is not None:
            discount_amount = money(item.get("discount"))
            if item.get("discount_percent") is not None:
                discount_amount += money(
                    Decimal(str(quantity))
                    * Decimal(str(unit_price))
                    * Decimal(str(item["discount_percent"]))
                    / Decimal("100")
                )
            calculated = money(
                Decimal(str(quantity)) * Decimal(str(unit_price)) - discount_amount
            )
            comparison_value = taxable_value
            if comparison_value is None and not item_tax and money(invoice.get("total_tax")) == 0:
                comparison_value = amount
            if comparison_value is not None and calculated != money(comparison_value):
                errors.append(
                    f"Item {index}: quantity x unit price less discount is {calculated}, "
                    f"but the taxable amount is {money(comparison_value)}."
                )
        if taxable_value is not None:
            item_sum += money(taxable_value)
        elif amount is not None and not item_tax and money(invoice.get("total_tax")) == 0:
            item_sum += money(amount)
        elif amount is not None:
            item_sum_comparable = False

    subtotal = money(invoice.get("subtotal"))
    if subtotal == 0 and item_sum_comparable and item_sum != 0:
        subtotal = item_sum
    if subtotal != 0 and item_sum != 0 and item_sum_comparable and subtotal != item_sum:
        errors.append(f"Subtotal is {subtotal}, but item taxable amounts sum to {item_sum}.")

    total_tax = money(invoice.get("total_tax"))
    tax_parts = sum(
        (money(invoice.get("cgst")), money(invoice.get("sgst")), money(invoice.get("igst"))),
        Decimal("0"),
    )
    if total_tax != 0 and tax_parts != 0 and total_tax != tax_parts:
        errors.append("Total tax does not equal CGST + SGST + IGST.")

    grand_total = money(invoice.get("grand_total"))
    calculated_total = subtotal + (tax_parts if tax_parts != 0 else total_tax)
    if grand_total != 0 and calculated_total != 0 and grand_total != calculated_total:
        errors.append(
            f"Grand total is {grand_total}, but subtotal + tax is {calculated_total}."
        )
    if grand_total != 0 and (grand_total < 0 or grand_total > Decimal("10000000")):
        warnings.append("Grand total is negative or suspiciously large.")

    status = "Validation Failed" if errors else "Needs Attention" if warnings or missing else "Verified"

    return {
        "status": status,
        "missing_fields": missing,
        "errors": errors,
        "warnings": warnings,
    }
