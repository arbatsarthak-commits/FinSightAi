from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Iterable


MONEY = Decimal("0.01")
ROUNDING_TOLERANCE = Decimal("0.50")


def money(value) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value))
        if not amount.is_finite():
            return None
        return amount.quantize(MONEY, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return None


def valid_date(value: str | None) -> bool:
    if not value:
        return False
    for fmt in (
        "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%m/%d/%Y",
        "%d-%m-%y", "%d/%m/%y", "%d.%m.%y", "%d %b %Y", "%d %B %Y",
        "%d %b %y", "%d %B %y",
    ):
        try:
            datetime.strptime(value, fmt)
            return True
        except ValueError:
            continue
    return False


def _recorded_money(
    value,
    field: str,
    errors: list[str],
) -> Decimal | None:
    amount = money(value)
    if value is not None and amount is None:
        errors.append(f"{field.replace('_', ' ').capitalize()} is not a valid monetary amount.")
    return amount


def _recorded_decimal(value, field: str, errors: list[str]) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value))
        if amount.is_finite():
            return amount
    except (InvalidOperation, ValueError):
        pass
    errors.append(f"{field.replace('_', ' ').capitalize()} is not a valid number.")
    return None


def validate_invoice(invoice: dict, existing_invoice_numbers: Iterable[str] = ()) -> dict:
    warnings: list[str] = []
    errors: list[str] = []
    missing: list[str] = []

    for field in ("invoice_number", "invoice_date", "vendor_name"):
        value = invoice.get(field)
        if not isinstance(value, str) or not value.strip():
            missing.append(field)
    if invoice.get("grand_total") is None:
        missing.append("grand_total")

    if invoice.get("invoice_date") and not valid_date(invoice["invoice_date"]):
        warnings.append("Invoice date is invalid or ambiguous.")
    if invoice.get("due_date") and not valid_date(invoice["due_date"]):
        warnings.append("Due date is invalid or ambiguous.")

    number = invoice.get("invoice_number")
    existing_numbers = {str(value).strip().lower() for value in existing_invoice_numbers}
    if number and str(number).strip().lower() in existing_numbers:
        warnings.append("A confirmed invoice with this invoice number already exists.")

    monetary_fields = (
        "subtotal", "cgst", "sgst", "igst", "total_tax", "round_off", "grand_total"
    )
    totals = {
        field: _recorded_money(invoice.get(field), field, errors)
        for field in monetary_fields
    }

    items = invoice.get("items") or []
    if not items and totals["subtotal"] is None:
        warnings.append("Subtotal or line items are missing; financial totals could not be reconciled.")

    taxable_amounts: list[Decimal] = []
    gross_amounts: list[Decimal] = []
    for index, item in enumerate(items, start=1):
        quantity = _recorded_decimal(item.get("quantity"), f"Item {index} quantity", errors)
        unit_price = _recorded_money(item.get("unit_price"), f"Item {index} unit price", errors)
        taxable_value = _recorded_money(
            item.get("taxable_value"), f"Item {index} taxable value", errors
        )
        amount = _recorded_money(item.get("amount"), f"Item {index} amount", errors)
        discount = _recorded_money(item.get("discount"), f"Item {index} discount", errors)
        discount_percent = item.get("discount_percent")
        percent = _recorded_decimal(
            discount_percent, f"Item {index} discount percentage", errors
        )

        if taxable_value is not None:
            taxable_amounts.append(taxable_value)
        elif item.get("amount_basis") == "taxable" and amount is not None:
            taxable_amounts.append(amount)
        else:
            taxable_amounts = []

        if amount is not None:
            gross_amounts.append(amount)
        else:
            gross_amounts = []

        if quantity is None or unit_price is None:
            continue
        calculated = quantity * unit_price
        if discount is not None:
            calculated -= discount
        if percent is not None:
            calculated -= (
                quantity * unit_price * percent / Decimal("100")
            ).quantize(MONEY, rounding=ROUND_HALF_UP)
        calculated = calculated.quantize(MONEY, rounding=ROUND_HALF_UP)

        comparable = taxable_value
        if comparable is None and item.get("amount_basis") in {"taxable", "gross"}:
            comparable = amount
        if comparable is not None and calculated != comparable:
            if taxable_value is not None or item.get("amount_basis") == "taxable":
                errors.append(
                    f"Item {index}: quantity x unit price less recorded discount is "
                    f"{calculated}, but the taxable amount is {comparable}."
                )
            else:
                warnings.append(
                    f"Item {index}: quantity x unit price does not reconcile to the "
                    "reported amount; its tax/discount basis is uncertain."
                )

    all_taxable_values = bool(items) and len(taxable_amounts) == len(items)
    all_gross_amounts = bool(items) and len(gross_amounts) == len(items)
    item_taxable_sum = sum(taxable_amounts, Decimal("0")) if all_taxable_values else None
    item_gross_sum = sum(gross_amounts, Decimal("0")) if all_gross_amounts else None
    subtotal = totals["subtotal"]
    grand_total = totals["grand_total"]

    if subtotal is not None:
        if item_taxable_sum is not None and subtotal != item_taxable_sum:
            errors.append(
                f"Subtotal is {subtotal}, but item taxable amounts sum to {item_taxable_sum}."
            )
        elif (
            item_taxable_sum is None
            and item_gross_sum is not None
            and item_gross_sum != subtotal
            and item_gross_sum != grand_total
        ):
            errors.append(
                "Subtotal does not reconcile to the stored line-item amounts or grand total."
            )
        elif item_taxable_sum is None and item_gross_sum is None and items:
            warnings.append(
                "Line-item values are incomplete or have an unknown amount basis; "
                "subtotal could not be reconciled."
            )
    elif items:
        warnings.append(
            "Subtotal is missing; the line-item values cannot be reconciled to it "
            "without an identified taxable-value basis."
        )

    components = [totals[field] for field in ("cgst", "sgst", "igst")]
    all_components_present = all(value is not None for value in components)
    any_component_present = any(value is not None for value in components)
    component_sum = (
        sum(components, Decimal("0")) if all_components_present else None
    )
    total_tax = totals["total_tax"]

    if any_component_present and not all_components_present:
        warnings.append("The GST component breakdown is incomplete; review CGST, SGST, and IGST.")
    if total_tax is None and any_component_present:
        warnings.append("Total tax is missing; the GST components cannot be fully reconciled.")
    if total_tax is not None and any_component_present and not all_components_present:
        warnings.append("The partial GST component breakdown cannot be reconciled to total tax.")
    if total_tax is not None and all_components_present and total_tax != component_sum:
        errors.append("Total tax does not equal CGST + SGST + IGST.")
    if total_tax is not None and total_tax != 0 and not any_component_present:
        warnings.append("Tax components are missing; review the GST breakdown.")

    if grand_total is not None and (grand_total < 0 or grand_total > Decimal("10000000")):
        warnings.append("Grand total is negative or suspiciously large.")

    subtotal_basis = subtotal if subtotal is not None else item_taxable_sum
    tax_basis = total_tax if total_tax is not None else component_sum
    round_off = totals["round_off"]
    tax_inclusive = invoice.get("tax_inclusive")

    if grand_total is not None and subtotal_basis is not None:
        if tax_inclusive is True:
            expected = subtotal_basis + (round_off if round_off is not None else Decimal("0"))
            difference = grand_total - expected
            if difference == 0:
                pass
            elif round_off is None and abs(difference) <= ROUNDING_TOLERANCE:
                warnings.append(
                    "Grand total differs from the tax-inclusive subtotal by a round-off-sized "
                    "amount, but round-off was not recorded."
                )
            else:
                errors.append(
                    "Grand total does not reconcile to the tax-inclusive subtotal and recorded round-off."
                )
        elif tax_basis is not None:
            expected = subtotal_basis + tax_basis
            if round_off is not None:
                expected += round_off
                if grand_total != expected:
                    errors.append(
                        f"Grand total is {grand_total}, but subtotal + tax + round-off is {expected}."
                    )
            elif grand_total == expected:
                pass
            elif tax_basis != 0 and grand_total == subtotal_basis:
                errors.append(
                    "Grand total equals subtotal even though tax is separately recorded; "
                    "confirm the tax-inclusive basis before verification."
                )
            elif abs(grand_total - expected) <= ROUNDING_TOLERANCE:
                warnings.append(
                    "Grand total differs from subtotal plus tax by a round-off-sized amount; "
                    "the round-off value was not extracted."
                )
            else:
                errors.append(
                    f"Grand total is {grand_total}, but subtotal + tax is {expected}."
                )
        elif tax_inclusive is False and round_off is not None:
            expected = subtotal_basis + round_off
            if grand_total != expected:
                errors.append(
                    "Grand total does not reconcile to the tax-exclusive subtotal and recorded round-off."
                )
        elif tax_inclusive is not False and grand_total == subtotal_basis:
            pass
        else:
            warnings.append(
                "Tax or subtotal basis is incomplete; grand-total reconciliation was not assumed."
            )

    status = "Validation Failed" if errors else "Needs Attention" if warnings or missing else "Verified"
    return {
        "status": status,
        "missing_fields": missing,
        "errors": errors,
        "warnings": warnings,
    }
