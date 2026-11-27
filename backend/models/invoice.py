from typing import Literal, Optional
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class InvoiceItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    description: Optional[str] = None
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    discount: Optional[float] = None
    discount_percent: Optional[float] = None
    taxable_value: Optional[float] = None
    cgst: Optional[float] = None
    sgst: Optional[float] = None
    igst: Optional[float] = None
    amount: Optional[float] = None
    amount_basis: Optional[Literal["taxable", "gross", "unknown"]] = None
    category: str = "Other"

    @model_validator(mode="before")
    @classmethod
    def split_percentage_discount(cls, value):
        if not isinstance(value, dict):
            return value
        for field in ("discount", "discount_percent"):
            discount = value.get(field)
            if not isinstance(discount, str) or not discount.strip().endswith("%"):
                continue
            try:
                percentage = float(discount.strip()[:-1].strip())
            except ValueError:
                continue
            value = value.copy()
            value[field] = percentage if field == "discount_percent" else None
            if field == "discount" and value.get("discount_percent") is None:
                value["discount_percent"] = percentage
        return value

    @field_validator(
        "quantity", "unit_price", "discount", "discount_percent", "taxable_value",
        "cgst", "sgst", "igst", "amount",
    )
    @classmethod
    def amount_must_be_finite(cls, value):
        if value is not None and (value != value or value in (float("inf"), float("-inf"))):
            raise ValueError("Amount must be finite.")
        return value

    @field_validator("category", mode="before")
    @classmethod
    def normalize_category(cls, value):
        if not isinstance(value, str) or not value.strip():
            return "Other"
        categories = {
            "food": "food",
            "logistics": "logistics",
            "drinks": "drinks",
            "travel": "travel",
            "grocery expense": "grocery expense",
            "utilities": "utilities",
        }
        return categories.get(value.strip().lower(), "Other")


class InvoiceData(BaseModel):
    model_config = ConfigDict(extra="ignore")

    invoice_number: Optional[str] = None
    order_number: Optional[str] = None
    pack_number: Optional[str] = None
    invoice_date: Optional[str] = None
    due_date: Optional[str] = None
    vendor_name: Optional[str] = None
    vendor_gstin: Optional[str] = None
    customer_name: Optional[str] = None
    customer_gstin: Optional[str] = None
    items: list[InvoiceItem] = Field(default_factory=list)
    subtotal: Optional[float] = None
    cgst: Optional[float] = None
    sgst: Optional[float] = None
    igst: Optional[float] = None
    total_tax: Optional[float] = None
    round_off: Optional[float] = None
    grand_total: Optional[float] = None
    tax_inclusive: Optional[bool] = None
    currency: Optional[str] = None
    payment_status: Optional[str] = None

    @field_validator("invoice_date", "due_date", mode="before")
    @classmethod
    def normalize_date(cls, value):
        if not isinstance(value, str) or not value.strip():
            return value
        for fmt in (
            "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y",
            "%m/%d/%Y", "%d-%m-%y", "%d/%m/%y",
            "%d %b %Y", "%d %B %Y", "%d %b %y", "%d %B %y",
        ):
            try:
                return datetime.strptime(value.strip(), fmt).date().isoformat()
            except ValueError:
                continue
        return value

    @field_validator(
        "subtotal", "cgst", "sgst", "igst", "total_tax", "round_off", "grand_total",
    )
    @classmethod
    def totals_must_be_finite(cls, value):
        if value is not None and (value != value or value in (float("inf"), float("-inf"))):
            raise ValueError("Amount must be finite.")
        return value
