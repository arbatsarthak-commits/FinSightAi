import json
import re
import time
import uuid
from datetime import date
from pathlib import Path
from typing import Any

import requests

from backend.database.database import db_connection, record_performance_metrics


INTENTS = {
    "spend_total",
    "spend_monthly",
    "spend_yearly",
    "vendor_top",
    "vendor_frequency",
    "category_top",
    "tax_total",
    "gst_breakdown",
    "average_total",
    "vendor_invoices",
    "amount_threshold",
    "invoice_detail",
    "line_item_search",
    "vendor_comparison",
    "month_comparison",
    "pending_invoices",
    "monthly_top",
    "category_spend",
    "unknown",
}

_MONTHS = {
    name.lower(): number for number, name in enumerate(
        ("January", "February", "March", "April", "May", "June", "July",
         "August", "September", "October", "November", "December"),
        start=1,
    )
}
_INVOICE_COLUMNS = (
    "id, invoice_number, invoice_date, vendor_name, grand_total, total_tax, "
    "validation_status, source_file"
)


def _currency(value: float | int | None) -> str:
    amount = float(value or 0)
    whole, _, fraction = f"{amount:.2f}".partition(".")
    if len(whole) > 3:
        last_three = whole[-3:]
        prefix = whole[:-3]
        groups = []
        while prefix:
            groups.insert(0, prefix[-2:])
            prefix = prefix[:-2]
        whole = ",".join(groups + [last_three])
    return f"₹{whole}.{fraction}"


def _month_bounds(year: int, month: int) -> tuple[str, str]:
    start = date(year, month, 1)
    end = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
    return start.isoformat(), end.isoformat()


def _history_context(history: list[dict]) -> dict:
    for item in reversed(history[-8:]):
        if item.get("role") == "assistant" and isinstance(item.get("context"), dict):
            return item["context"]
    return {}


def _explicit_months(text: str) -> list[tuple[int, int]]:
    lowered = text.lower()
    matches = []
    for name, month in _MONTHS.items():
        for match in re.finditer(rf"\b{name}\s+(20\d{{2}})\b", lowered):
            matches.append((int(match.group(1)), month, match.start()))
    matches.sort(key=lambda item: item[2])
    return [(year, month) for year, month, _ in matches[:2]]


def _period_from_text(text: str) -> dict[str, Any]:
    lowered = text.lower()
    explicit = _explicit_months(lowered)
    if explicit:
        year, month = explicit[0]
        return {"period": "month", "year": year, "month": month}
    year_match = re.search(r"\b(20\d{2})\b", lowered)
    if year_match and re.search(r"\b(?:year|annual|yearly|in|during|for)\b", lowered):
        return {"period": "year", "year": int(year_match.group(1))}
    today = date.today()
    if re.search(r"\b(?:last month|previous month)\b", lowered):
        year, month = (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
        return {"period": "month", "year": year, "month": month}
    if re.search(r"\b(?:this month|month to date|monthly)\b", lowered):
        return {"period": "month", "year": today.year, "month": today.month}
    if re.search(r"\b(?:this year|year to date|yearly|annual)\b", lowered):
        return {"period": "year", "year": today.year}
    if re.search(r"\b(?:last year|previous year)\b", lowered):
        return {"period": "year", "year": today.year - 1}
    return {"period": "all"}


def _deterministic_intent(question: str, history: list[dict]) -> dict[str, Any]:
    text = re.sub(r"\s+", " ", question.strip().lower())
    context = _history_context(history)
    invoice_reference = {}
    if context.get("invoice_number"):
        invoice_reference["invoice_number"] = context["invoice_number"]
    elif isinstance(context.get("invoice_id"), int) and context["invoice_id"] > 0:
        invoice_reference["invoice_id"] = context["invoice_id"]
    if invoice_reference and re.search(
        r"\b(?:its|that|this)\s+(?:line\s+items?|items?|products?|total|date|details?|invoice|bill)\b",
        text,
    ):
        return {"intent": "invoice_detail", **invoice_reference}
    if re.search(r"\b(?:its|their|that vendor'?s)\s+invoices\b", text) and context.get("vendor"):
        return {"intent": "vendor_invoices", "vendor": context["vendor"]}
    if re.search(r"\b(?:that|this|its)\s+(?:invoice|bill)\b", text) and context.get("invoice_number"):
        return {"intent": "invoice_detail", "invoice_number": context["invoice_number"]}

    if re.search(r"\b(?:pending|unverified|needs attention|awaiting review)\b", text):
        return {"intent": "pending_invoices"}

    months = _explicit_months(text)
    if len(months) >= 2 and re.search(r"\b(?:compare|comparison|versus|vs\.?)\b", text):
        return {"intent": "month_comparison", "months": months}
    if re.search(r"\b(?:compare|comparison|versus|vs\.?)\b", text) and re.search(r"\bmonth\b", text):
        return {"intent": "month_comparison", "months": []}

    if re.search(r"\b(?:compare|comparison|versus|vs\.?)\b", text) and re.search(r"\bvendor|supplier\b", text):
        match = re.search(
            r"(?:vendor|supplier)\s+(.+?)\s+(?:and|versus|vs\.?)\s+(?:vendor|supplier\s+)?"
            r"(.+?)(?:\s+(?:spend|payments|invoices|totals?)\b.*)?$",
            text,
        )
        if match:
            return {
                "intent": "vendor_comparison",
                "vendor_a": match.group(1).strip(" .?!"),
                "vendor_b": match.group(2).strip(" .?!"),
            }

    invoice_match = re.search(
        r"\b(?:invoice|bill)\s*(?:number|no\.?|#)\s*[:#-]?\s*([a-z0-9][a-z0-9/_-]{1,40})\b",
        text,
    )
    if invoice_match:
        return {"intent": "invoice_detail", "invoice_number": invoice_match.group(1)}

    search_match = re.search(
        r"\b(?:find|search for|show|list)\s+(?:the\s+)?"
        r"(?:line items?|products?|items?)\s+(?:containing|called|named|for)?\s*"
        r"['\"]?([a-z0-9][a-z0-9 .&/-]{1,60})['\"]?$",
        text,
    )
    if search_match:
        term = search_match.group(1).strip(" .?!'\"")
        if term not in {"from the invoice", "in the invoice", "invoices"}:
            return {"intent": "line_item_search", "term": term}

    if re.search(r"\b(?:highest|most expensive|largest)\b", text) and re.search(r"\bmonth\b", text):
        return {"intent": "monthly_top"}
    if re.search(r"\b(?:gst|tax)\b", text) and re.search(r"\b(?:breakdown|cgst|sgst|igst|split)\b", text):
        return {"intent": "gst_breakdown"}
    if re.search(r"\b(?:gst|tax)\b", text) and re.search(r"\b(?:paid|total|spend|expenditure)\b", text):
        return {"intent": "tax_total"}
    if re.search(r"\b(?:average|mean)\b", text) and re.search(r"\binvoice\b", text):
        return {"intent": "average_total"}
    if re.search(r"\b(?:top|highest|most)\b", text) and re.search(r"\bvendor|supplier\b", text):
        if re.search(r"\b(?:frequent|often|frequently|count|number of invoices|purchased)\b", text):
            return {"intent": "vendor_frequency"}
        return {"intent": "vendor_top"}
    if re.search(r"\b(?:top|highest|most)\b", text) and re.search(
        r"\b(?:category|categories|expense type)\b", text
    ):
        match = re.search(r"\btop\s+(\d+)\b", text)
        return {"intent": "category_top", "limit": min(10, max(1, int(match.group(1)))) if match else 5}
    if re.search(r"\b(?:above|over|greater than|more than|below|under|less than)\b", text):
        match = re.search(
            r"\b(above|over|greater than|more than|below|under|less than)\s*"
            r"(?:₹|rs\.?\s*)?([\d,]+(?:\.\d{1,2})?)",
            text,
        )
        if match:
            return {
                "intent": "amount_threshold",
                "operator": "below" if match.group(1) in {"below", "under", "less than"} else "above",
                "amount": float(match.group(2).replace(",", "")),
            }
    if re.search(r"\b(?:product|item|line item)\b", text) and re.search(r"\b(?:search|find|bought|purchased|contains?)\b", text):
        term = re.sub(
            r"\b(?:search|find|product|item|line items?|bought|purchased|contains?|invoices?|from|for)\b",
            " ",
            text,
        )
        term = re.sub(r"\s+", " ", term).strip(" .?!")
        if term:
            return {"intent": "line_item_search", "term": term[:80]}

    vendor_match = re.search(r"\b(?:invoices?|bills?)\s+(?:from|for)\s+(.+?)(?:\s+(?:this|last|in|above|below)\b.*)?$", text)
    if vendor_match:
        vendor = vendor_match.group(1).strip(" .?!")
        if vendor:
            return {"intent": "vendor_invoices", "vendor": vendor[:120]}
    if context.get("vendor") and re.search(r"\b(?:show|list|detail|invoice|spend|total)\b", text):
        return {"intent": "vendor_invoices", "vendor": context["vendor"]}

    category_match = re.search(r"\b(food|travel|utilities|logistics|grocery|drinks|electronics)\b", text)
    if category_match and re.search(r"\b(?:spend|spent|expenditure|how much)\b", text):
        return {"intent": "category_spend", "category": category_match.group(1)}

    period = _period_from_text(text)
    if re.search(r"\b(?:monthly|by month|per month|month wise)\b", text) and "expenditure" in text:
        return {"intent": "spend_monthly", **period}
    if period.get("period") == "year" and re.search(r"\b(?:spend|spent|expenditure|total)\b", text):
        return {"intent": "spend_yearly", **period}
    if re.search(r"\b(?:total|spend|spent|expenditure)\b", text):
        return {"intent": "spend_total", **period}
    if re.search(r"\b(?:uploaded|latest|recent|this)\s+(?:invoice|bill)\b", text):
        return {"intent": "invoice_detail", "latest": True}
    return {"intent": "unknown"}


def _model_intent(question: str, history: list[dict]) -> dict[str, Any]:
    from backend.llm.mistral_service import (
        OLLAMA_HOST,
        OLLAMA_MODEL,
        OLLAMA_REQUEST_LOCK,
        _OLLAMA_SESSION,
        _ensure_model_available,
    )

    if not OLLAMA_REQUEST_LOCK.acquire(blocking=False):
        raise RuntimeError("Ollama is busy with optional enrichment; retry this question shortly.")
    try:
        _ensure_model_available()
        prompt = (
            "Classify the question and recent conversation into one supported intent: "
            + ", ".join(sorted(INTENTS))
            + ". Return one JSON object with intent, vendor, category, amount, operator, "
            "limit, period, year, month, invoice_number, term, vendor_a, vendor_b. "
            "Do not calculate or invent financial values; values must be taken from the "
            "question or conversation. Return unknown if uncertain. Conversation: "
            + json.dumps(history[-6:], ensure_ascii=False)[:2000]
            + ". Question: "
            + question[:500]
        )
        response = _OLLAMA_SESSION.post(
            f"{OLLAMA_HOST.rstrip('/')}/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "format": "json",
                "stream": False,
                "keep_alive": "10m",
                "options": {"temperature": 0, "num_ctx": 1024, "num_predict": 100},
            },
            timeout=(3, 20),
        )
        response.raise_for_status()
        data = json.loads(response.json().get("response", ""))
    finally:
        OLLAMA_REQUEST_LOCK.release()

    if not isinstance(data, dict) or data.get("intent") not in INTENTS:
        return {"intent": "unknown"}
    result: dict[str, Any] = {"intent": data["intent"]}
    for field in ("vendor", "category", "term", "invoice_number", "vendor_a", "vendor_b"):
        value = data.get(field)
        if isinstance(value, str):
            result[field] = value[:120]
    if isinstance(data.get("amount"), (int, float)) and 0 <= data["amount"] <= 1_000_000_000:
        result["amount"] = float(data["amount"])
    if data.get("operator") in {"above", "below"}:
        result["operator"] = data["operator"]
    if isinstance(data.get("limit"), int):
        result["limit"] = min(10, max(1, data["limit"]))
    if isinstance(data.get("year"), int) and 1900 <= data["year"] <= 2200:
        result["year"] = data["year"]
    if isinstance(data.get("month"), int) and 1 <= data["month"] <= 12:
        result["month"] = data["month"]
    if data.get("period") in {"all", "month", "year"}:
        result["period"] = data["period"]
    return result


def _rows(
    db_path: str | Path,
    sql: str,
    parameters: tuple = (),
    timings: dict[str, float] | None = None,
) -> list[dict]:
    started = time.perf_counter()
    with db_connection(db_path) as connection:
        connection.set_progress_handler(lambda: 1, 500_000)
        cursor = connection.execute(sql, parameters)
        result = [dict(row) for row in cursor.fetchmany(200)]
    if timings is not None:
        timings["sql_execution_seconds"] += time.perf_counter() - started
    return result


def _date_filter(intent: dict[str, Any], date_column: str = "invoice_date") -> tuple[str, tuple]:
    period = intent.get("period", "all")
    if period == "month":
        year = intent.get("year", date.today().year)
        month = intent.get("month", date.today().month)
        start, end = _month_bounds(int(year), int(month))
        return f"{date_column} >= ? AND {date_column} < ?", (start, end)
    if period == "year":
        year = int(intent.get("year", date.today().year))
        return f"{date_column} >= ? AND {date_column} < ?", (
            f"{year:04d}-01-01", f"{year + 1:04d}-01-01",
        )
    return "1 = 1", ()


def _supporting_invoices(
    db_path: str | Path, where: str, parameters: tuple, timings: dict[str, float]
) -> tuple[list[dict], int]:
    count_rows = _rows(
        db_path, f"SELECT COUNT(*) AS count FROM invoices WHERE {where}", parameters, timings
    )
    invoices = _rows(
        db_path,
        f"SELECT {_INVOICE_COLUMNS} FROM invoices WHERE {where} "
        "ORDER BY invoice_date DESC, id DESC LIMIT 20",
        parameters,
        timings,
    )
    return invoices, int(count_rows[0]["count"])


def _provisional_spend_summary(
    db_path: str | Path,
    scope_filter: str,
    parameters: tuple,
    timings: dict[str, float],
) -> tuple[dict, list[dict]]:
    provisional = "(validation_status IS NULL OR validation_status != 'Verified')"
    rows = _rows(
        db_path,
        f"""SELECT COUNT(*) AS invoice_count,
                   COUNT(grand_total) AS priced_invoice_count,
                   COUNT(*) - COUNT(grand_total) AS missing_total_count,
                   SUM(grand_total) AS total
            FROM invoices
            WHERE {provisional} AND ({scope_filter})""",
        parameters,
        timings,
    )
    invoices, _ = _supporting_invoices(
        db_path, f"{provisional} AND ({scope_filter})", parameters, timings
    )
    return rows[0], invoices


def _provisional_spend_note(summary: dict) -> str:
    if not summary["invoice_count"]:
        return ""
    count = summary["invoice_count"]
    missing = summary["missing_total_count"]
    if summary["priced_invoice_count"]:
        note = (
            f" Provisional invoices, excluded from verified spend: "
            f"{summary['priced_invoice_count']} with recorded totals summing to "
            f"{_currency(summary['total'])}."
        )
    else:
        note = " Provisional invoices, excluded from verified spend, have no recorded totals."
    if missing:
        note += f" {missing} of {count} provisional invoice(s) have no recorded total."
    return note


def _tax_summary(
    db_path: str | Path,
    where: str,
    timings: dict[str, float],
) -> dict:
    rows = _rows(
        db_path,
        f"""SELECT SUM(total_tax) AS total,
                   COUNT(*) AS invoice_count,
                   COUNT(total_tax) AS recorded_count,
                   COUNT(*) - COUNT(total_tax) AS missing_count
            FROM invoices WHERE {where}""",
        timings=timings,
    )
    return rows[0]


def _provisional_tax_note(summary: dict) -> str:
    if not summary["invoice_count"]:
        return ""
    if summary["recorded_count"]:
        note = (
            f" Provisional invoices, excluded from verified tax, have recorded tax "
            f"totalling {_currency(summary['total'])} across "
            f"{summary['recorded_count']} invoice(s)."
        )
    else:
        note = " Provisional invoices, excluded from verified tax, have no recorded tax totals."
    if summary["missing_count"]:
        note += f" Tax is not recorded on {summary['missing_count']} provisional invoice(s)."
    return note


def _gst_breakdown(db_path: str | Path, where: str, timings: dict[str, float]) -> dict:
    rows = _rows(
        db_path,
        f"""SELECT SUM(cgst) AS cgst, COUNT(cgst) AS cgst_count,
                   SUM(sgst) AS sgst, COUNT(sgst) AS sgst_count,
                   SUM(igst) AS igst, COUNT(igst) AS igst_count,
                   SUM(total_tax) AS total_tax, COUNT(total_tax) AS total_tax_count,
                   COUNT(*) AS invoice_count
            FROM invoices WHERE {where}""",
        timings=timings,
    )
    return rows[0]


def _gst_value(value, count: int) -> str:
    return _currency(value) if count else "not recorded"


def _gst_missing_note(summary: dict, status: str) -> str:
    missing = [
        component.upper()
        for component in ("cgst", "sgst", "igst")
        if summary[f"{component}_count"] < summary["invoice_count"]
    ]
    if not missing:
        return ""
    return (
        f" GST components are not recorded for every {status} invoice "
        f"({', '.join(missing)})."
    )


def _answer_intent(
    db_path: str | Path, intent: dict[str, Any], timings: dict[str, float]
) -> tuple[str, list[dict], dict, dict]:
    name = intent["intent"]
    verified = "validation_status = 'Verified'"
    context: dict[str, Any] = {}
    support: list[dict] = []
    support_count = 0

    if name in {"spend_total", "spend_yearly"}:
        period_filter, period_parameters = _date_filter(intent)
        rows = _rows(
            db_path,
            f"""SELECT SUM(CASE WHEN validation_status = 'Verified' THEN grand_total END) AS total,
                       COUNT(CASE WHEN validation_status = 'Verified' AND grand_total IS NOT NULL THEN 1 END) AS count,
                       COUNT(CASE WHEN validation_status = 'Verified' AND grand_total IS NULL THEN 1 END) AS missing_verified_total_count
                FROM invoices WHERE {period_filter}""",
            period_parameters,
            timings,
        )
        provisional_summary, provisional_support = _provisional_spend_summary(
            db_path, period_filter, period_parameters, timings
        )
        verified_where = f"{verified} AND {period_filter}"
        support, support_count = _supporting_invoices(
            db_path, verified_where, period_parameters, timings
        )
        calculation = {
            "total": rows[0]["total"],
            "count": rows[0]["count"],
            "supporting_invoice_count": support_count,
            "provisional_summary": provisional_summary,
            "provisional_supporting_invoice_count": len(provisional_support),
            "provisional_supporting_invoices": provisional_support,
            "missing_verified_total_count": rows[0]["missing_verified_total_count"],
        }
        if not rows[0]["count"]:
            period_name = "the selected period" if period_filter != "1 = 1" else "any period"
            answer = f"No verified invoice totals are recorded for {period_name}."
            if rows[0]["missing_verified_total_count"]:
                answer += (
                    f" {rows[0]['missing_verified_total_count']} verified invoice(s) "
                    "have no recorded total."
                )
            answer += _provisional_spend_note(provisional_summary)
            return answer, support, context, calculation
        if intent.get("period") == "month":
            label = date(int(intent["year"]), int(intent["month"]), 1).strftime("%B %Y")
        elif intent.get("period") == "year":
            label = str(intent["year"])
        else:
            label = "all time"
        answer = (
            f"Verified expenditure for {label} is {_currency(rows[0]['total'])} "
            f"across {rows[0]['count']} invoices."
        )
        if rows[0]["missing_verified_total_count"]:
            answer += (
                f" {rows[0]['missing_verified_total_count']} verified invoice(s) "
                "have no recorded total and are excluded from the sum."
            )
        answer += _provisional_spend_note(provisional_summary)
        return answer, support, context, calculation

    if name == "spend_monthly":
        year = int(intent.get("year", date.today().year))
        parameters = (f"{year:04d}-01-01", f"{year + 1:04d}-01-01")
        rows = _rows(
            db_path,
            "SELECT substr(invoice_date,1,7) AS month, SUM(grand_total) AS amount, "
            "COUNT(grand_total) AS invoice_count, "
            "COUNT(*) - COUNT(grand_total) AS missing_total_count FROM invoices WHERE "
            + verified + " AND invoice_date >= ? AND invoice_date < ? "
            "GROUP BY substr(invoice_date,1,7) ORDER BY month",
            parameters,
            timings,
        )
        provisional_summary, provisional_support = _provisional_spend_summary(
            db_path, "invoice_date >= ? AND invoice_date < ?", parameters, timings
        )
        provisional_months = _rows(
            db_path,
            """SELECT substr(invoice_date,1,7) AS month,
                      SUM(grand_total) AS amount,
                      COUNT(*) AS invoice_count,
                      COUNT(grand_total) AS priced_invoice_count
               FROM invoices
               WHERE (validation_status IS NULL OR validation_status != 'Verified')
                 AND invoice_date >= ? AND invoice_date < ?
               GROUP BY substr(invoice_date,1,7) ORDER BY month""",
            parameters,
            timings,
        )
        where = f"{verified} AND invoice_date >= ? AND invoice_date < ?"
        support, support_count = _supporting_invoices(db_path, where, parameters, timings)
        calculation = {
            "months": rows,
            "supporting_invoice_count": support_count,
            "provisional_summary": provisional_summary,
            "provisional_months": provisional_months,
            "provisional_supporting_invoice_count": len(provisional_support),
            "provisional_supporting_invoices": provisional_support,
        }
        if not rows:
            answer = f"No dated verified invoices are recorded for {year}."
            answer += _provisional_spend_note(provisional_summary)
            return answer, support, context, calculation
        answer = f"Monthly verified expenditure for {year}: " + "; ".join(
            f"{row['month']}: "
            f"{_currency(row['amount']) if row['amount'] is not None else 'amount not recorded'} "
            f"({row['invoice_count']} invoices with totals)"
            for row in rows
        )
        missing_verified_totals = sum(row["missing_total_count"] for row in rows)
        if missing_verified_totals:
            answer += (
                f" {missing_verified_totals} verified invoice(s) have no recorded total "
                "and are excluded from the monthly sums."
            )
        answer += _provisional_spend_note(provisional_summary)
        return answer, support, context, calculation

    if name == "tax_total":
        result = _tax_summary(db_path, verified, timings)
        provisional_where = "(validation_status IS NULL OR validation_status != 'Verified')"
        provisional_summary = _tax_summary(db_path, provisional_where, timings)
        support, support_count = _supporting_invoices(db_path, verified, (), timings)
        provisional_support, _ = _supporting_invoices(
            db_path, provisional_where, (), timings
        )
        calculation = {
            "tax_total": result["total"],
            "count": result["recorded_count"],
            "verified_invoice_count": result["invoice_count"],
            "missing_tax_count": result["missing_count"],
            "provisional_summary": provisional_summary,
            "supporting_invoice_count": support_count,
            "provisional_supporting_invoice_count": len(provisional_support),
            "provisional_supporting_invoices": provisional_support,
        }
        if not result["recorded_count"]:
            answer = "No verified invoices have recorded tax amounts."
        else:
            answer = (
                f"Recorded GST/tax on verified invoices is {_currency(result['total'])}, "
                f"from {result['recorded_count']} invoice(s)."
            )
        if result["missing_count"]:
            answer += f" Tax is not recorded on {result['missing_count']} verified invoice(s)."
        answer += _provisional_tax_note(provisional_summary)
        return answer, support, context, calculation

    if name == "gst_breakdown":
        result = _gst_breakdown(db_path, verified, timings)
        provisional_where = "(validation_status IS NULL OR validation_status != 'Verified')"
        provisional_summary = _gst_breakdown(db_path, provisional_where, timings)
        support, support_count = _supporting_invoices(db_path, verified, (), timings)
        provisional_support, _ = _supporting_invoices(
            db_path, provisional_where, (), timings
        )
        has_verified_tax = any(result[f"{field}_count"] for field in ("cgst", "sgst", "igst", "total_tax"))
        if not has_verified_tax:
            answer = "No verified invoices contain a recorded GST breakdown."
        else:
            answer = (
                f"Recorded GST on verified invoices: "
                f"CGST {_gst_value(result['cgst'], result['cgst_count'])}, "
                f"SGST {_gst_value(result['sgst'], result['sgst_count'])}, "
                f"IGST {_gst_value(result['igst'], result['igst_count'])}; "
                f"recorded total tax {_gst_value(result['total_tax'], result['total_tax_count'])}."
            )
        answer += _gst_missing_note(result, "verified")
        if provisional_summary["invoice_count"]:
            if any(
                provisional_summary[f"{field}_count"]
                for field in ("cgst", "sgst", "igst", "total_tax")
            ):
                answer += (
                    " Provisional GST, excluded from verified totals: "
                    f"CGST {_gst_value(provisional_summary['cgst'], provisional_summary['cgst_count'])}, "
                    f"SGST {_gst_value(provisional_summary['sgst'], provisional_summary['sgst_count'])}, "
                    f"IGST {_gst_value(provisional_summary['igst'], provisional_summary['igst_count'])}; "
                    f"recorded total tax {_gst_value(provisional_summary['total_tax'], provisional_summary['total_tax_count'])}."
                )
            else:
                answer += " Provisional invoices are excluded and have no recorded GST components."
            answer += _gst_missing_note(provisional_summary, "provisional")
        calculation = {
            **result,
            "provisional_summary": provisional_summary,
            "supporting_invoice_count": support_count,
            "provisional_supporting_invoice_count": len(provisional_support),
            "provisional_supporting_invoices": provisional_support,
        }
        return answer, support, context, calculation

    if name == "average_total":
        rows = _rows(
            db_path,
            f"SELECT AVG(grand_total) AS average, COUNT(grand_total) AS count, "
            f"COUNT(*) - COUNT(grand_total) AS missing_total_count FROM invoices WHERE {verified}",
            timings=timings,
        )
        provisional_where = "(validation_status IS NULL OR validation_status != 'Verified')"
        provisional_rows = _rows(
            db_path,
            f"""SELECT AVG(grand_total) AS average, COUNT(grand_total) AS count,
                       COUNT(*) AS invoice_count,
                       COUNT(*) - COUNT(grand_total) AS missing_total_count
                FROM invoices WHERE {provisional_where}""",
            timings=timings,
        )
        support, support_count = _supporting_invoices(db_path, verified, (), timings)
        provisional_support, _ = _supporting_invoices(
            db_path, provisional_where, (), timings
        )
        provisional = provisional_rows[0]
        calculation = {
            "provisional_summary": provisional,
            "provisional_supporting_invoice_count": len(provisional_support),
            "provisional_supporting_invoices": provisional_support,
            "supporting_invoice_count": support_count,
        }
        if not rows[0]["count"]:
            answer = "No verified invoice totals are available to calculate an average."
        else:
            answer = (
                f"The average verified invoice value is {_currency(rows[0]['average'])} "
                f"across {rows[0]['count']} invoices."
            )
            calculation.update(rows[0])
        if provisional["count"]:
            answer += (
                f" The provisional average is {_currency(provisional['average'])} "
                f"across {provisional['count']} recorded totals, excluded from verified results."
            )
        elif provisional["invoice_count"]:
            answer += " Provisional invoices have no recorded totals for an average."
        return answer, support, context, calculation

    if name in {"vendor_top", "vendor_frequency"}:
        aggregate = (
            "COUNT(*) AS invoice_count, COUNT(grand_total) AS priced_invoice_count, "
            "SUM(grand_total) AS amount"
        )
        order = "invoice_count DESC, vendor_name COLLATE NOCASE" if name == "vendor_frequency" else "amount DESC, vendor_name COLLATE NOCASE"
        rows = _rows(
            db_path,
            f"SELECT vendor_name AS vendor, {aggregate} FROM invoices WHERE {verified} "
            f"AND vendor_name IS NOT NULL GROUP BY vendor_name ORDER BY {order} LIMIT 1",
            timings=timings,
        )
        provisional_where = "(validation_status IS NULL OR validation_status != 'Verified')"
        provisional_aggregate = (
            "COUNT(*) AS invoice_count, COUNT(grand_total) AS priced_invoice_count, "
            "SUM(grand_total) AS amount"
        )
        provisional_order = (
            "invoice_count DESC, vendor_name COLLATE NOCASE"
            if name == "vendor_frequency"
            else "amount DESC, vendor_name COLLATE NOCASE"
        )
        provisional_rows = _rows(
            db_path,
            f"SELECT vendor_name AS vendor, {provisional_aggregate} FROM invoices "
            f"WHERE {provisional_where} AND vendor_name IS NOT NULL "
            f"GROUP BY vendor_name ORDER BY {provisional_order} LIMIT 1",
            timings=timings,
        )
        provisional_vendor_support = []
        if provisional_rows:
            provisional_vendor_support, _ = _supporting_invoices(
                db_path,
                f"{provisional_where} AND vendor_name = ?",
                (provisional_rows[0]["vendor"],),
                timings,
            )
        calculation = {
            "provisional_vendor": provisional_rows[0] if provisional_rows else None,
            "provisional_supporting_invoice_count": len(provisional_vendor_support),
            "provisional_supporting_invoices": provisional_vendor_support,
        }
        if not rows:
            answer = "There are no verified invoices with vendor names to compare."
            if provisional_rows:
                provisional_vendor = provisional_rows[0]
                answer += (
                    f" Provisional records are led by {provisional_vendor['vendor']} "
                    f"with {provisional_vendor['invoice_count']} invoice(s); this is not "
                    "included in verified vendor results."
                )
            return answer, support, context, calculation
        vendor = rows[0]["vendor"]
        where = f"{verified} AND vendor_name = ?"
        support, support_count = _supporting_invoices(db_path, where, (vendor,), timings)
        context["vendor"] = vendor
        if name == "vendor_frequency":
            answer = f"{vendor} appears most often, with {rows[0]['invoice_count']} verified invoices."
        elif rows[0]["amount"] is None:
            answer = f"{vendor} has verified invoices, but no verified invoice totals are recorded."
        else:
            answer = f"{vendor} is the highest-spending vendor at {_currency(rows[0]['amount'])}."
        if provisional_rows:
            provisional_vendor = provisional_rows[0]
            if name == "vendor_frequency":
                answer += (
                    f" The most frequent provisional vendor is {provisional_vendor['vendor']} "
                    f"with {provisional_vendor['invoice_count']} invoice(s), not verified."
                )
            elif provisional_vendor["amount"] is not None:
                answer += (
                    f" The largest known provisional vendor total is "
                    f"{provisional_vendor['vendor']} at {_currency(provisional_vendor['amount'])}, "
                    "excluded from verified spend."
                )
            else:
                answer += (
                    f" Provisional records for {provisional_vendor['vendor']} have no "
                    "recorded totals and are excluded from verified spend."
                )
        calculation.update(rows[0])
        calculation["supporting_invoice_count"] = support_count
        return answer, support, context, calculation

    if name == "category_top":
        limit = min(10, max(1, int(intent.get("limit", 5))))
        rows = _rows(
            db_path,
            """SELECT COALESCE(ii.category,'Other') AS category,
                      SUM(COALESCE(ii.taxable_value,ii.amount)) AS amount,
                      COUNT(COALESCE(ii.taxable_value,ii.amount)) AS priced_item_count
               FROM invoice_items ii JOIN invoices i ON i.id=ii.invoice_id
               WHERE i.validation_status='Verified'
               GROUP BY COALESCE(ii.category,'Other')
               ORDER BY amount DESC LIMIT ?""",
            (limit,),
            timings,
        )
        provisional_rows = _rows(
            db_path,
            """SELECT COALESCE(ii.category,'Other') AS category,
                      SUM(COALESCE(ii.taxable_value,ii.amount)) AS amount,
                      COUNT(*) AS item_count,
                      COUNT(COALESCE(ii.taxable_value,ii.amount)) AS priced_item_count
               FROM invoice_items ii JOIN invoices i ON i.id=ii.invoice_id
               WHERE (i.validation_status IS NULL OR i.validation_status != 'Verified')
               GROUP BY COALESCE(ii.category,'Other')
               ORDER BY amount DESC LIMIT ?""",
            (limit,),
            timings,
        )
        provisional_support = []
        if provisional_rows:
            categories = [row["category"] for row in provisional_rows]
            placeholders = ",".join("?" for _ in categories)
            provisional_where = (
                "(validation_status IS NULL OR validation_status != 'Verified') AND id IN "
                "(SELECT invoice_id FROM invoice_items "
                f"WHERE COALESCE(category,'Other') IN ({placeholders}))"
            )
            provisional_support, _ = _supporting_invoices(
                db_path, provisional_where, tuple(categories), timings
            )
        calculation = {
            "provisional_categories": provisional_rows,
            "provisional_supporting_invoice_count": len(provisional_support),
            "provisional_supporting_invoices": provisional_support,
        }
        if not rows:
            answer = "No verified invoice line items are available for category totals."
            if provisional_rows:
                answer += " Provisional category totals are available separately and are not verified."
            return answer, support, context, calculation
        answer = "Top verified expense categories: " + "; ".join(
            f"{row['category']} "
            f"({_currency(row['amount']) if row['priced_item_count'] else 'amount not recorded'})"
            for row in rows
        )
        if provisional_rows:
            answer += " Provisional categories (excluded from verified totals): " + "; ".join(
                f"{row['category']} "
                f"({_currency(row['amount']) if row['amount'] is not None else 'amount not recorded'})"
                for row in provisional_rows
            ) + "."
        categories = [row["category"] for row in rows]
        context["category"] = categories[0]
        placeholders = ",".join("?" for _ in categories)
        where = (
            "validation_status = 'Verified' AND id IN "
            "(SELECT invoice_id FROM invoice_items "
            f"WHERE COALESCE(category,'Other') IN ({placeholders}))"
        )
        support, support_count = _supporting_invoices(db_path, where, tuple(categories), timings)
        calculation.update({
            "categories": rows,
            "supporting_invoice_count": support_count,
        })
        return answer, support, context, calculation

    if name == "category_spend":
        category = str(intent.get("category") or "").strip()
        if not category:
            return "Which expense category should I look up?", support, context, {}
        match_filter = (
            "(lower(COALESCE(ii.category,'')) LIKE ? OR "
            "lower(COALESCE(ii.description,'')) LIKE ?)"
        )
        where = (
            "i.validation_status='Verified' AND " + match_filter
        )
        params = (f"%{category.lower()}%", f"%{category.lower()}%")
        rows = _rows(
            db_path,
            "SELECT SUM(COALESCE(ii.taxable_value,ii.amount)) AS total, "
            "COUNT(DISTINCT i.id) AS invoice_count, "
            "COUNT(COALESCE(ii.taxable_value,ii.amount)) AS priced_item_count, "
            "COUNT(*) AS item_count FROM invoice_items ii "
            "JOIN invoices i ON i.id=ii.invoice_id WHERE " + where,
            params,
            timings,
        )
        provisional_where = (
            "(i.validation_status IS NULL OR i.validation_status != 'Verified') AND "
            + match_filter
        )
        provisional_rows = _rows(
            db_path,
            "SELECT SUM(COALESCE(ii.taxable_value,ii.amount)) AS total, "
            "COUNT(DISTINCT i.id) AS invoice_count, "
            "COUNT(COALESCE(ii.taxable_value,ii.amount)) AS priced_item_count, "
            "COUNT(*) AS item_count FROM invoice_items ii "
            "JOIN invoices i ON i.id=ii.invoice_id WHERE " + provisional_where,
            params,
            timings,
        )
        support_where = (
            "validation_status='Verified' AND id IN "
            "(SELECT i.id FROM invoice_items ii JOIN invoices i ON i.id=ii.invoice_id "
            f"WHERE {match_filter})"
        )
        support, support_count = _supporting_invoices(db_path, support_where, params, timings)
        provisional_support_where = (
            "(validation_status IS NULL OR validation_status != 'Verified') AND id IN "
            "(SELECT i.id FROM invoice_items ii JOIN invoices i ON i.id=ii.invoice_id "
            f"WHERE {match_filter})"
        )
        provisional_support, _ = _supporting_invoices(
            db_path, provisional_support_where, params, timings
        )
        context["category"] = category
        calculation = {
            "provisional_summary": provisional_rows[0],
            "provisional_supporting_invoice_count": len(provisional_support),
            "provisional_supporting_invoices": provisional_support,
        }
        if not rows[0]["invoice_count"]:
            answer = f"No verified line items match {category}."
        elif not rows[0]["priced_item_count"]:
            answer = f"Verified line items matching {category} have no recorded amounts."
        else:
            answer = (
                f"Verified spending matching {category} is {_currency(rows[0]['total'])} "
                f"across {rows[0]['invoice_count']} invoices."
            )
            if rows[0]["item_count"] > rows[0]["priced_item_count"]:
                answer += (
                    f" {rows[0]['item_count'] - rows[0]['priced_item_count']} matching "
                    "line item(s) have no recorded amount."
                )
        provisional = provisional_rows[0]
        if provisional["invoice_count"]:
            if provisional["priced_item_count"]:
                answer += (
                    f" Provisional items matching {category} total "
                    f"{_currency(provisional['total'])} across "
                    f"{provisional['invoice_count']} invoice(s), excluded from verified spend."
                )
                if provisional["item_count"] > provisional["priced_item_count"]:
                    answer += (
                        f" {provisional['item_count'] - provisional['priced_item_count']} "
                        "provisional line item(s) have no recorded amount."
                    )
            else:
                answer += (
                    f" Provisional items matching {category} have no recorded amounts "
                    "and are excluded from verified spend."
                )
        calculation.update(rows[0])
        calculation["supporting_invoice_count"] = support_count
        return answer, support, context, calculation

    if name == "monthly_top":
        rows = _rows(
            db_path,
            f"SELECT substr(invoice_date,1,7) AS month, SUM(grand_total) AS amount, "
            f"COUNT(grand_total) AS priced_invoice_count "
            f"FROM invoices WHERE {verified} AND invoice_date IS NOT NULL "
            "GROUP BY substr(invoice_date,1,7) ORDER BY amount DESC LIMIT 1",
            timings=timings,
        )
        provisional_where = (
            "(validation_status IS NULL OR validation_status != 'Verified') "
            "AND invoice_date IS NOT NULL"
        )
        provisional_rows = _rows(
            db_path,
            f"""SELECT substr(invoice_date,1,7) AS month,
                       SUM(grand_total) AS amount,
                       COUNT(*) AS invoice_count,
                       COUNT(grand_total) AS priced_invoice_count
                FROM invoices WHERE {provisional_where}
                GROUP BY substr(invoice_date,1,7)
                ORDER BY amount DESC LIMIT 1""",
            timings=timings,
        )
        provisional_support = []
        if provisional_rows:
            provisional_bounds = _month_bounds(
                int(provisional_rows[0]["month"][:4]),
                int(provisional_rows[0]["month"][5:7]),
            )
            provisional_support, _ = _supporting_invoices(
                db_path,
                "(validation_status IS NULL OR validation_status != 'Verified') "
                "AND invoice_date >= ? AND invoice_date < ?",
                provisional_bounds,
                timings,
            )
        calculation = {
            "provisional_month": provisional_rows[0] if provisional_rows else None,
            "provisional_supporting_invoice_count": len(provisional_support),
            "provisional_supporting_invoices": provisional_support,
        }
        if not rows:
            answer = "There are no dated verified invoices to compare."
            if provisional_rows:
                provisional_month = provisional_rows[0]
                amount = (
                    _currency(provisional_month["amount"])
                    if provisional_month["amount"] is not None
                    else "no totals recorded"
                )
                answer += (
                    f" The largest provisional month is {provisional_month['month']} "
                    f"with {amount}, excluded from verified comparisons."
                )
            return answer, support, context, calculation
        bounds = _month_bounds(int(rows[0]["month"][:4]), int(rows[0]["month"][5:7]))
        where = f"{verified} AND invoice_date >= ? AND invoice_date < ?"
        support, support_count = _supporting_invoices(db_path, where, bounds, timings)
        answer = (
            f"{rows[0]['month']} had the highest verified expenditure at "
            f"{_currency(rows[0]['amount']) if rows[0]['amount'] is not None else 'no totals recorded'}."
        )
        if provisional_rows:
            provisional_month = provisional_rows[0]
            if provisional_month["amount"] is None:
                answer += (
                    f" Provisional invoices in {provisional_month['month']} have no "
                    "recorded totals and are excluded from verified comparisons."
                )
            else:
                answer += (
                    f" The largest known provisional month is {provisional_month['month']} "
                    f"at {_currency(provisional_month['amount'])}, excluded from verified spend."
                )
        calculation.update(rows[0])
        calculation["supporting_invoice_count"] = support_count
        return answer, support, context, calculation

    if name == "month_comparison":
        months = intent.get("months") or []
        if len(months) < 2:
            today = date.today()
            last_year, last_month = (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
            months = [(last_year, last_month), (today.year, today.month)]
        if not all(
            isinstance(value, (tuple, list)) and len(value) == 2
            and 1900 <= int(value[0]) <= 2200 and 1 <= int(value[1]) <= 12
            for value in months[:2]
        ):
            return "Please specify two months to compare.", support, context, {}
        comparisons = []
        filters = []
        parameters: list[str] = []
        for year, month in months[:2]:
            start, end = _month_bounds(int(year), int(month))
            parameters.extend((start, end))
            filters.append("(invoice_date >= ? AND invoice_date < ?)")
            comparisons.append(date(int(year), int(month), 1).strftime("%B %Y"))
        rows = _rows(
            db_path,
            f"SELECT substr(invoice_date,1,7) AS month, SUM(grand_total) AS amount, "
            "COUNT(*) AS count, COUNT(grand_total) AS priced_invoice_count "
            f"FROM invoices WHERE {verified} AND ({' OR '.join(filters)}) "
            "GROUP BY substr(invoice_date,1,7)",
            tuple(parameters),
            timings,
        )
        provisional_where = (
            "(validation_status IS NULL OR validation_status != 'Verified') "
            f"AND ({' OR '.join(filters)})"
        )
        provisional_rows = _rows(
            db_path,
            f"""SELECT substr(invoice_date,1,7) AS month,
                       SUM(grand_total) AS amount,
                       COUNT(*) AS count,
                       COUNT(grand_total) AS priced_invoice_count
                FROM invoices WHERE {provisional_where}
                GROUP BY substr(invoice_date,1,7)""",
            tuple(parameters),
            timings,
        )
        amounts = {row["month"]: row for row in rows}
        support_where = f"{verified} AND ({' OR '.join(filters)})"
        support, support_count = _supporting_invoices(db_path, support_where, tuple(parameters), timings)
        provisional_support, _ = _supporting_invoices(
            db_path, provisional_where, tuple(parameters), timings
        )
        provisional_amounts = {row["month"]: row for row in provisional_rows}
        formatted = []
        for year, month in months[:2]:
            key = f"{int(year):04d}-{int(month):02d}"
            value = amounts.get(key)
            formatted.append(
                f"{date(int(year), int(month), 1).strftime('%B %Y')}: "
                + (
                    _currency(value["amount"])
                    if value and value["amount"] is not None
                    else "no recorded verified spend"
                )
            )
        answer = (
            "Verified monthly expenditure comparison: " + "; ".join(formatted) + "."
            if rows
            else "No dated verified invoices match those months."
        )
        if provisional_rows:
            provisional_formatted = []
            for year, month in months[:2]:
                key = f"{int(year):04d}-{int(month):02d}"
                value = provisional_amounts.get(key)
                provisional_formatted.append(
                    f"{date(int(year), int(month), 1).strftime('%B %Y')}: "
                    + (_currency(value["amount"]) if value and value["amount"] is not None
                       else "no recorded provisional spend")
                )
            answer += (
                " Provisional monthly totals (not verified): "
                + "; ".join(provisional_formatted)
                + "."
            )
        return (
            answer,
            support,
            context,
            {
                "months": rows,
                "provisional_months": provisional_rows,
                "supporting_invoice_count": support_count,
                "provisional_supporting_invoice_count": len(provisional_support),
                "provisional_supporting_invoices": provisional_support,
            },
        )

    if name == "vendor_comparison":
        vendors = [str(intent.get(key, "")).strip() for key in ("vendor_a", "vendor_b")]
        if not all(vendors):
            return "Name two vendors to compare.", support, context, {}
        rows = _rows(
            db_path,
            f"SELECT vendor_name AS vendor, SUM(grand_total) AS amount, COUNT(*) AS invoice_count "
            f"FROM invoices WHERE {verified} AND vendor_name IN (?, ?) "
            "GROUP BY vendor_name ORDER BY amount DESC",
            tuple(vendors),
            timings,
        )
        provisional_where = (
            "(validation_status IS NULL OR validation_status != 'Verified') "
            "AND vendor_name IN (?, ?)"
        )
        provisional_rows = _rows(
            db_path,
            f"""SELECT vendor_name AS vendor, SUM(grand_total) AS amount,
                       COUNT(*) AS invoice_count,
                       COUNT(grand_total) AS priced_invoice_count
                FROM invoices WHERE {provisional_where}
                GROUP BY vendor_name ORDER BY amount DESC""",
            tuple(vendors),
            timings,
        )
        where = f"{verified} AND vendor_name IN (?, ?)"
        support, support_count = _supporting_invoices(db_path, where, tuple(vendors), timings)
        provisional_support, _ = _supporting_invoices(
            db_path, provisional_where, tuple(vendors), timings
        )
        if rows:
            answer = "Verified vendor comparison: " + "; ".join(
                f"{row['vendor']} "
                f"{_currency(row['amount']) if row['amount'] is not None else 'amount not recorded'} "
                f"({row['invoice_count']} invoices)"
                for row in rows
            ) + "."
        else:
            answer = "No verified invoices were found for those vendors."
        if provisional_rows:
            answer += " Provisional vendor totals (not verified): " + "; ".join(
                f"{row['vendor']} "
                f"{_currency(row['amount']) if row['amount'] is not None else 'amount not recorded'} "
                f"({row['invoice_count']} invoices)"
                for row in provisional_rows
            ) + "."
        return (
            answer,
            support,
            context,
            {
                "vendors": rows,
                "provisional_vendors": provisional_rows,
                "supporting_invoice_count": support_count,
                "provisional_supporting_invoice_count": len(provisional_support),
                "provisional_supporting_invoices": provisional_support,
            },
        )

    if name == "amount_threshold":
        amount = float(intent.get("amount", 0))
        operator = ">" if intent.get("operator") != "below" else "<"
        where = f"grand_total {operator} ?"
        rows = _rows(
            db_path,
            f"SELECT COUNT(*) AS count FROM invoices WHERE {where}",
            (amount,),
            timings,
        )
        support, support_count = _supporting_invoices(db_path, where, (amount,), timings)
        direction = "above" if operator == ">" else "below"
        if not rows[0]["count"]:
            return f"No invoices are recorded {direction} {_currency(amount)}.", support, context, {}
        return (
            f"Found {rows[0]['count']} invoice(s) {direction} {_currency(amount)}.",
            support,
            context,
            {"count": rows[0]["count"], "threshold": amount, "supporting_invoice_count": support_count},
        )

    if name == "vendor_invoices":
        vendor = str(intent.get("vendor") or "").strip()
        if not vendor:
            return "Which vendor should I look up?", support, context, {}
        where = "lower(vendor_name) LIKE lower(?)"
        support, support_count = _supporting_invoices(db_path, where, (f"%{vendor}%",), timings)
        if not support_count:
            return f"No invoices were found for vendor {vendor}.", support, {"vendor": vendor}, {}
        return (
            f"Found {support_count} invoice(s) for {vendor}.",
            support,
            {"vendor": vendor},
            {"count": support_count, "supporting_invoice_count": support_count},
        )

    if name == "invoice_detail":
        invoice_number = str(intent.get("invoice_number") or "").strip()
        if intent.get("latest"):
            where = "1 = 1"
            params: tuple = ()
        elif isinstance(intent.get("invoice_id"), int) and intent["invoice_id"] > 0:
            where = "id = ?"
            params = (intent["invoice_id"],)
        elif invoice_number:
            where = "lower(invoice_number) LIKE lower(?)"
            params = (f"%{invoice_number}%",)
        else:
            return "Please provide an invoice number or ask for the latest uploaded invoice.", support, context, {}
        support, support_count = _supporting_invoices(db_path, where, params, timings)
        if not support_count:
            return "No matching invoice is stored in the database.", support, context, {}
        if intent.get("latest"):
            support = _rows(
                db_path,
                f"SELECT {_INVOICE_COLUMNS} FROM invoices ORDER BY id DESC LIMIT 1",
                timings=timings,
            )
        invoice = support[0]
        items = _rows(
            db_path,
            "SELECT description, quantity, unit_price, taxable_value, amount, category "
            "FROM invoice_items WHERE invoice_id = ? ORDER BY id",
            (invoice["id"],),
            timings,
        )
        context["invoice_id"] = invoice["id"]
        context["invoice_number"] = invoice.get("invoice_number")
        answer = (
            f"Invoice {invoice.get('invoice_number') or invoice['id']} from "
            f"{invoice.get('vendor_name') or 'an unknown vendor'} is dated "
            f"{invoice.get('invoice_date') or 'not recorded'}; stored total is "
            f"{_currency(invoice['grand_total']) if invoice.get('grand_total') is not None else 'not recorded'} "
            f"({invoice.get('validation_status') or 'status unknown'}). "
            f"{len(items)} line item(s) are stored."
        )
        context["line_items"] = items
        return answer, [invoice], context, {"line_items": items, "supporting_invoice_count": support_count}

    if name == "line_item_search":
        term = str(intent.get("term") or "").strip()
        if not term:
            return "What product or line-item description should I search for?", support, context, {}
        rows = _rows(
            db_path,
            """SELECT i.id, i.invoice_number, i.invoice_date, i.vendor_name, i.grand_total,
                      i.validation_status, ii.description, ii.quantity, ii.unit_price,
                      ii.taxable_value, ii.amount, ii.category
               FROM invoice_items ii JOIN invoices i ON i.id=ii.invoice_id
               WHERE lower(COALESCE(ii.description,'')) LIKE lower(?)
               ORDER BY i.invoice_date DESC, i.id DESC LIMIT 20""",
            (f"%{term}%",),
            timings,
        )
        count_rows = _rows(
            db_path,
            "SELECT COUNT(*) AS count FROM invoice_items WHERE lower(COALESCE(description,'')) LIKE lower(?)",
            (f"%{term}%",),
            timings,
        )
        support = rows
        support_count = int(count_rows[0]["count"])
        if not support_count:
            return f"No stored invoice line items match {term}.", support, context, {}
        return (
            f"Found {support_count} stored line item(s) matching {term}.",
            support,
            context,
            {"count": support_count, "supporting_invoice_count": len({row['id'] for row in rows})},
        )

    if name == "pending_invoices":
        where = "(validation_status IS NULL OR validation_status != 'Verified')"
        support, support_count = _supporting_invoices(db_path, where, (), timings)
        if not support_count:
            return "There are no invoices awaiting review.", support, context, {}
        return (
            f"Found {support_count} invoice(s) awaiting review or not verified.",
            support,
            context,
            {"count": support_count, "supporting_invoice_count": support_count},
        )

    return (
        "I couldn't map that question to a supported database query. Try asking about "
        "expenditure, monthly or yearly spend, GST, vendors, categories, invoice numbers, "
        "line items, amount thresholds, or pending invoices.",
        support,
        context,
        {},
    )


def answer_question(
    db_path: str | Path, question: str, history: list[dict] | None = None
) -> dict:
    history = history if isinstance(history, list) else []
    timings = {"intent_detection_seconds": 0.0, "sql_execution_seconds": 0.0}
    request_id = str(uuid.uuid4())
    intent_started = time.perf_counter()
    intent = _deterministic_intent(question, history)
    model_warning = None
    if intent["intent"] == "unknown":
        try:
            intent = _model_intent(question, history)
        except (requests.RequestException, json.JSONDecodeError, RuntimeError, ValueError) as exc:
            intent = {"intent": "unknown"}
            model_warning = str(exc)
    timings["intent_detection_seconds"] = time.perf_counter() - intent_started

    response_started = time.perf_counter()
    answer, rows, context, calculation = _answer_intent(db_path, intent, timings)
    if model_warning:
        answer += f" Question interpretation was unavailable: {model_warning}"
    timings["response_generation_seconds"] = max(
        0.0,
        time.perf_counter() - response_started - timings["sql_execution_seconds"],
    )
    rounded_timings = {key: round(value, 6) for key, value in timings.items()}
    record_performance_metrics(
        db_path,
        [
            {"stage": stage, "duration_seconds": value}
            for stage, value in rounded_timings.items()
        ],
        request_id=request_id,
    )
    response = {
        "answer": answer,
        "rows": rows,
        "supporting_invoices": rows,
        "context": context,
        "intent": intent["intent"],
        "calculation": calculation,
        "performance": rounded_timings,
    }
    provisional_support = calculation.pop("provisional_supporting_invoices", None)
    if provisional_support is not None:
        response["provisional_invoices"] = provisional_support
    return response
