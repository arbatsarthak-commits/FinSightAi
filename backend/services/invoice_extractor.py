import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from backend.models.invoice import InvoiceData


_DATE_PATTERN = re.compile(
    r"\b(?:\d{4}[./-]\d{1,2}[./-]\d{1,2}|\d{1,2}[./-]\d{1,2}[./-]\d{2,4}"
    r"|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{2,4})\b"
)
_GSTIN_PATTERN = re.compile(
    r"\b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b",
    re.IGNORECASE,
)
_NUMBER_PATTERN = re.compile(r"(?<![A-Za-z])\(?-?\d[\d,]*(?:\.\d{1,2})?\)?")
_LABELS = {
    "invoice_number": ("invoice number", "invoice no", "bill number", "bill no", "bill"),
    "invoice_date": ("invoice date", "bill date", "date of invoice", "date"),
    "due_date": ("due date", "payment due", "due on"),
    "vendor_name": ("vendor", "supplier", "seller", "billed by", "from"),
    "customer_name": ("billed to", "bill to", "buyer", "customer", "ship to"),
    "subtotal": ("taxable value", "taxable amount", "subtotal", "sub total"),
    "cgst": ("cgst", "central tax"),
    "sgst": ("sgst", "state tax"),
    "igst": ("igst", "integrated tax"),
    "total_tax": ("total tax", "gst total", "total gst", "tax amount"),
    "grand_total": (
        "grand total",
        "invoice total",
        "amount payable",
        "total payable",
        "net payable",
        "total amount",
        "total",
    ),
}
_TABLE_HEADERS = {
    "description": ("description", "particulars", "product", "item", "service"),
    "quantity": ("quantity", "qty", "units"),
    "unit_price": ("unit price", "rate", "price"),
    "taxable_value": ("taxable value", "taxable amount", "assessable value"),
    "cgst": ("cgst",),
    "sgst": ("sgst",),
    "igst": ("igst",),
    "amount": ("line total", "amount", "amt", "total"),
}
_OCR_HEADER_CORRECTIONS = {"tten": "item", "oty": "qty", "ant": "amt"}
_TABLE_END = re.compile(
    r"\b(?:sub\s*total|grand\s*total|total\s*payable|amount\s*payable|"
    r"cgst|sgst|igst|terms\s+and\s+conditions)\b",
    re.IGNORECASE,
)


def _line_groups(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[int, int, int, int], list[dict[str, Any]]] = {}
    ungrouped: list[dict[str, Any]] = []
    for word in words:
        if all(key in word for key in ("block_num", "par_num", "line_num")):
            key = (
                int(word.get("page", 1)),
                int(word["block_num"]),
                int(word["par_num"]),
                int(word["line_num"]),
            )
            grouped.setdefault(key, []).append(word)
        else:
            ungrouped.append(word)

    lines = []
    for key, line_words in grouped.items():
        line_words.sort(key=lambda word: int(word.get("left", 0)))
        lines.append(_make_line(key[0], line_words))

    for word in sorted(
        ungrouped,
        key=lambda item: (int(item.get("page", 1)), int(item.get("top", 0)), int(item.get("left", 0))),
    ):
        page = int(word.get("page", 1))
        top = int(word.get("top", 0))
        height = max(1, int(word.get("height", 1)))
        match = next(
            (
                line for line in reversed(lines)
                if line["page"] == page
                and abs(line["top"] - top) <= max(height, line["height"]) * 0.6
            ),
            None,
        )
        if match is None:
            lines.append(_make_line(page, [word]))
        else:
            match["words"].append(word)
            match["words"].sort(key=lambda item: int(item.get("left", 0)))
            match.update(_line_geometry(match["words"]))
            match["text"] = " ".join(str(item.get("text", "")) for item in match["words"])

    return sorted(lines, key=lambda line: (line["page"], line["top"], line["left"]))


def _line_geometry(words: list[dict[str, Any]]) -> dict[str, int]:
    left = min(int(word.get("left", 0)) for word in words)
    top = min(int(word.get("top", 0)) for word in words)
    right = max(int(word.get("left", 0)) + int(word.get("width", 0)) for word in words)
    bottom = max(int(word.get("top", 0)) + int(word.get("height", 0)) for word in words)
    return {"left": left, "top": top, "width": right - left, "height": bottom - top}


def _make_line(page: int, words: list[dict[str, Any]]) -> dict[str, Any]:
    words = sorted(words, key=lambda word: int(word.get("left", 0)))
    return {
        "page": page,
        "words": words,
        "text": " ".join(str(word.get("text", "")) for word in words),
        **_line_geometry(words),
    }


def _line_confidence(words: list[dict[str, Any]]) -> float:
    values = []
    for word in words:
        try:
            value = float(word.get("confidence", -1))
        except (TypeError, ValueError):
            continue
        if value >= 0:
            values.append(min(1.0, value / 100.0))
    return round(sum(values) / len(values), 3) if values else 0.0


def _evidence(line: dict[str, Any] | None, source: str = "tesseract") -> dict[str, Any]:
    if line is None:
        return {"source": "missing", "line": None, "page": None, "bbox": None, "confidence": 0.0}
    return {
        "source": source,
        "line": line["text"][:300],
        "page": line["page"],
        "bbox": {
            "left": line["left"],
            "top": line["top"],
            "width": line["width"],
            "height": line["height"],
        },
        "word_texts": [str(word.get("text", "")) for word in line["words"]],
        "confidence": _line_confidence(line["words"]),
    }


def _find_label(text: str, aliases: tuple[str, ...]) -> tuple[int, str] | None:
    lowered = text.lower()
    for alias in sorted(aliases, key=len, reverse=True):
        match = re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", lowered)
        if match:
            return match.end(), alias
    return None


def _label_value(
    lines: list[dict[str, Any]], aliases: tuple[str, ...]
) -> tuple[str | None, dict[str, Any] | None]:
    for index, line in enumerate(lines):
        found = _find_label(line["text"], aliases)
        if not found:
            continue
        if aliases == _LABELS["invoice_number"] and re.search(
            r"\bbill\s*to\b", line["text"], re.IGNORECASE
        ):
            continue
        if (
            aliases == _LABELS["grand_total"]
            and found[1] == "total"
            and re.match(r"\s*(?:tax|gst)\b", line["text"][found[0]:], re.IGNORECASE)
        ):
            continue
        if (
            "date" in aliases
            and found[1] == "date"
            and re.search(r"\b(?:due|expiry|validity)\b", line["text"], re.IGNORECASE)
        ):
            continue
        remainder = line["text"][found[0]:].strip(" \t:：-#")
        if remainder:
            return remainder, line
        if index + 1 < len(lines) and lines[index + 1]["page"] == line["page"]:
            next_line = lines[index + 1]
            if not _find_label(next_line["text"], tuple(alias for values in _LABELS.values() for alias in values)):
                return next_line["text"], next_line
    return None, None


def _parse_date(value: str | None) -> str | None:
    if not value:
        return None
    match = _DATE_PATTERN.search(value)
    if not match:
        return None
    token = match.group(0)
    formats = (
        "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d",
        "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y",
        "%d-%m-%y", "%d/%m/%y", "%d.%m.%y",
        "%d %b %Y", "%d %B %Y", "%d %b %y", "%d %B %y",
    )
    for format_string in formats:
        try:
            return datetime.strptime(token, format_string).date().isoformat()
        except ValueError:
            continue
    return None


def _parse_amount(value: str | None) -> float | None:
    if not value:
        return None
    matches = _NUMBER_PATTERN.findall(value.replace("−", "-"))
    if not matches:
        return None
    token = matches[-1].strip("()").replace(",", "")
    try:
        amount = Decimal(token)
    except InvalidOperation:
        return None
    return float(amount) if amount.is_finite() else None


def _labelled_amount(lines: list[dict[str, Any]], field: str) -> tuple[float | None, dict[str, Any] | None]:
    value, line = _label_value(lines, _LABELS[field])
    if value:
        value = re.sub(r"\b\d+(?:[.,]\d+)?\s*%", " ", value)
    return _parse_amount(value), line


def _header_positions(line: dict[str, Any]) -> dict[str, float]:
    text = line["text"].lower()
    positions: dict[str, float] = {}
    used_words: set[int] = set()
    normalized_words = []
    for word in line["words"]:
        token = re.sub(r"[^a-z]", "", str(word.get("text", "")).lower())
        normalized_words.append(_OCR_HEADER_CORRECTIONS.get(token, token))
    for field, aliases in _TABLE_HEADERS.items():
        for alias in sorted(aliases, key=len, reverse=True):
            parts = [re.sub(r"[^a-z]", "", part) for part in alias.lower().split()]
            for start in range(len(normalized_words) - len(parts) + 1):
                if normalized_words[start:start + len(parts)] == parts:
                    indexes = set(range(start, start + len(parts)))
                    if indexes & used_words:
                        continue
                    selected = line["words"][start:start + len(parts)]
                    positions[field] = sum(
                        int(word.get("left", 0)) + int(word.get("width", 0)) / 2
                        for word in selected
                    ) / len(selected)
                    used_words.update(indexes)
                    break
            if field in positions:
                break
            if alias in {"description", "particulars", "product", "item", "service"}:
                match = re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", text)
                if match:
                    center = line["left"] + (match.start() + match.end()) / max(1, len(text)) * line["width"]
                    positions[field] = center
                    break
    return positions


def _find_table_header(lines: list[dict[str, Any]]) -> tuple[int, dict[str, float]] | None:
    for index, line in enumerate(lines):
        columns = _header_positions(line)
        numeric_columns = set(columns) - {"description"}
        if "description" in columns and len(numeric_columns) >= 1:
            return index, columns
    return None


def _columns_for_line(
    line: dict[str, Any], columns: dict[str, float]
) -> dict[str, list[dict[str, Any]]]:
    ordered = sorted(columns.items(), key=lambda item: item[1])
    boundaries = [
        (ordered[index][1] + ordered[index + 1][1]) / 2
        for index in range(len(ordered) - 1)
    ]
    cells = {field: [] for field, _ in ordered}
    for word in line["words"]:
        center = int(word.get("left", 0)) + int(word.get("width", 0)) / 2
        column_index = 0
        while column_index < len(boundaries) and center >= boundaries[column_index]:
            column_index += 1
        cells[ordered[column_index][0]].append(word)
    return cells


def _cell_value(words: list[dict[str, Any]]) -> str:
    return " ".join(str(word.get("text", "")) for word in words).strip()


def _table_items(
    lines: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    items = []
    item_evidence = []
    for page in sorted({line["page"] for line in lines}):
        page_lines = [line for line in lines if line["page"] == page]
        header = _find_table_header(page_lines)
        if not header:
            continue
        header_index, columns = header
        for line in page_lines[header_index + 1:]:
            if _TABLE_END.search(line["text"]):
                break
            cells = _columns_for_line(line, columns)
            description_words = cells.get("description", [])
            description = _cell_value(description_words)
            if not description or not re.search(r"[A-Za-z]", description):
                continue
            item: dict[str, Any] = {"description": description, "category": "Other"}
            item_fields: dict[str, Any] = {
                "description": _evidence({**line, "words": description_words}),
            }
            numeric_value_found = False
            for field in (
                "quantity", "unit_price", "taxable_value", "cgst", "sgst", "igst", "amount"
            ):
                field_words = cells.get(field, [])
                value = _parse_amount(_cell_value(field_words))
                if value is not None:
                    item[field] = value
                    numeric_value_found = True
                    cell_line = {**line, "words": field_words}
                    cell_line.update(_line_geometry(field_words))
                    item_fields[field] = _evidence(cell_line)
                else:
                    item_fields[field] = _evidence(None)
            if (
                not numeric_value_found
                and items
                and item_evidence[-1]["fields"]["description"]["page"] == page
                and line["top"] - item_evidence[-1]["fields"]["description"]["bbox"]["top"] < 120
            ):
                previous = items[-1]
                previous["description"] = f"{previous['description']} {description}".strip()
                previous_evidence = item_evidence[-1]["fields"]["description"]
                previous_evidence["line"] = (
                    f"{previous_evidence['line']} / {description}"[:300]
                )
                previous_evidence["confidence"] = round(
                    (previous_evidence["confidence"] + _line_confidence(description_words)) / 2,
                    3,
                )
                continue
            if "amount" not in item and "taxable_value" in item:
                item["amount"] = item["taxable_value"]
                item_fields["amount"] = item_fields["taxable_value"]
            items.append(item)
            item_evidence.append({
                "item": len(items),
                "fields": item_fields,
                "confidence": round(_line_confidence(line["words"]), 3),
            })
    return items, item_evidence


def _party_gstin(lines: list[dict[str, Any]]) -> tuple[str | None, str | None, dict[str, Any] | None, dict[str, Any] | None]:
    vendor_value = customer_value = None
    vendor_line = customer_line = None
    for line in lines:
        match = _GSTIN_PATTERN.search(line["text"])
        if not match:
            continue
        if re.search(r"\b(?:buyer|customer|bill\s*to)\b", line["text"], re.IGNORECASE):
            customer_value, customer_line = match.group(0).upper(), line
        elif vendor_value is None:
            vendor_value, vendor_line = match.group(0).upper(), line
    return vendor_value, customer_value, vendor_line, customer_line


def _vendor_fallback(lines: list[dict[str, Any]], gstin_line: dict[str, Any] | None) -> tuple[str | None, dict[str, Any] | None]:
    candidates = [
        line for line in lines
        if re.search(r"[A-Za-z]{3}", line["text"])
        and not re.search(r"\d", line["text"])
        and not re.search(
            r"\b(?:invoice|tax|gst|date|bill|phone|mobile|email|address|number|no\.?|"
            r"description|particulars|quantity|qty|rate|amount|item|product)\b",
            line["text"],
            re.IGNORECASE,
        )
    ]
    if gstin_line:
        above = [
            line for line in candidates
            if line["page"] == gstin_line["page"] and line["top"] < gstin_line["top"]
        ]
        if above:
            return above[0]["text"][:120], above[0]
    return (candidates[0]["text"][:120], candidates[0]) if candidates else (None, None)


def extract_invoice_from_ocr(ocr: dict[str, Any]) -> dict[str, Any]:
    words = ocr.get("words", [])
    lines = _line_groups(words if isinstance(words, list) else [])
    raw_text = str(ocr.get("text", ""))
    if not lines and raw_text:
        lines = [
            _make_line(1, [{"text": value, "left": 0, "top": index * 24, "width": len(value) * 7,
                            "height": 20, "confidence": 0}])
            for index, value in enumerate(raw_text.splitlines())
            if value.strip()
        ]

    payload: dict[str, Any] = {
        "items": [],
        "currency": "INR" if re.search(r"(?:₹|\bINR\b|\bRs\.?)", raw_text, re.IGNORECASE) else None,
    }
    evidence: dict[str, Any] = {}
    confidence: dict[str, float] = {}

    for field in ("invoice_number", "invoice_date", "due_date", "vendor_name", "customer_name"):
        value, line = _label_value(lines, _LABELS[field])
        if field in {"invoice_date", "due_date"}:
            value = _parse_date(value)
        elif field == "invoice_number" and value:
            match = re.search(r"[A-Za-z0-9][A-Za-z0-9/_-]{1,40}", value)
            value = match.group(0) if match else None
        elif field in {"vendor_name", "customer_name"} and value:
            value = re.sub(r"\s+", " ", value).strip(" :-")
            value = value[:120] or None
        payload[field] = value
        evidence[field] = _evidence(line)
        confidence[field] = evidence[field]["confidence"] if value else 0.0

    vendor_gstin, customer_gstin, vendor_gstin_line, customer_gstin_line = _party_gstin(lines)
    payload["vendor_gstin"] = vendor_gstin
    payload["customer_gstin"] = customer_gstin
    for field, value, line in (
        ("vendor_gstin", vendor_gstin, vendor_gstin_line),
        ("customer_gstin", customer_gstin, customer_gstin_line),
    ):
        evidence[field] = _evidence(line)
        confidence[field] = evidence[field]["confidence"] if value else 0.0

    if not payload.get("vendor_name"):
        vendor_name, vendor_line = _vendor_fallback(lines, vendor_gstin_line)
        payload["vendor_name"] = vendor_name
        evidence["vendor_name"] = _evidence(vendor_line, "layout heuristic" if vendor_line else "missing")
        confidence["vendor_name"] = min(0.65, evidence["vendor_name"]["confidence"]) if vendor_name else 0.0

    for field in ("subtotal", "cgst", "sgst", "igst", "total_tax", "grand_total"):
        value, line = _labelled_amount(lines, field)
        payload[field] = value
        evidence[field] = _evidence(line)
        confidence[field] = evidence[field]["confidence"] if value is not None else 0.0

    items, item_evidence = _table_items(lines)
    payload["items"] = items
    evidence["items"] = item_evidence
    confidence["items"] = (
        round(sum(item["confidence"] for item in item_evidence) / len(item_evidence), 3)
        if item_evidence else 0.0
    )

    payment_line = next(
        (line for line in lines if re.search(r"\b(?:paid|unpaid|pending|due)\b", line["text"], re.IGNORECASE)),
        None,
    )
    if payment_line:
        status_match = re.search(r"\b(paid|unpaid|pending|due)\b", payment_line["text"], re.IGNORECASE)
        payload["payment_status"] = status_match.group(1).capitalize() if status_match else None
        evidence["payment_status"] = _evidence(payment_line)
        confidence["payment_status"] = evidence["payment_status"]["confidence"]
    else:
        payload["payment_status"] = None
        evidence["payment_status"] = _evidence(None)
        confidence["payment_status"] = 0.0

    invoice = InvoiceData.model_validate(payload).model_dump()
    return {
        "invoice": invoice,
        "evidence": evidence,
        "confidence": confidence,
    }
