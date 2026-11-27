import json
import re
import requests
from datetime import date
from pathlib import Path

from backend.database.database import db_connection


INTENTS = {
    "spend_total",
    "vendor_top",
    "category_top",
    "tax_total",
    "vendor_invoices",
    "monthly_top",
    "average_total",
    "pending_invoices",
    "month_comparison",
    "amount_threshold",
    "category_spend",
    "vendor_frequency",
    "unknown",
}


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
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)
    return start.isoformat(), end.isoformat()


def _period_bounds(period: str) -> tuple[str, str] | None:
    today = date.today()
    if period == "this_month":
        return _month_bounds(today.year, today.month)
    if period == "last_month":
        year, month = (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
        return _month_bounds(year, month)
    return None


def _history_context(history: list[dict]) -> dict:
    for item in reversed(history[-8:]):
        if item.get("role") == "assistant" and isinstance(item.get("context"), dict):
            return item["context"]
    return {}


def _deterministic_intent(question: str, history: list[dict]) -> dict:
    text = re.sub(r"\s+", " ", question.strip().lower())
    context = _history_context(history)
    if re.search(r"\b(?:its|their|that vendor'?s)\s+invoices\b", text) and context.get("vendor"):
        return {"intent": "vendor_invoices", "vendor": context["vendor"]}

    if re.search(r"\b(?:pending|unverified|needs attention)\b", text):
        return {"intent": "pending_invoices"}
    if re.search(r"\b(?:compare|comparison)\b", text) and re.search(r"\bmonth\b", text):
        return {"intent": "month_comparison"}
    if re.search(r"\b(?:top|highest|most)\b", text) and re.search(r"\bvendor|supplier\b", text):
        if re.search(r"\b(?:frequent|often|frequently|count|number of invoices)\b", text):
            return {"intent": "vendor_frequency"}
        return {"intent": "vendor_top"}
    if re.search(r"\b(?:highest|most expensive|largest)\b", text) and re.search(r"\bmonth\b", text):
        return {"intent": "monthly_top"}
    if re.search(r"\b(?:top|highest|most)\b", text) and re.search(r"\b(?:categor|expense type)\b", text):
        match = re.search(r"\btop\s+(\d+)\b", text)
        return {"intent": "category_top", "limit": min(10, max(1, int(match.group(1)))) if match else 5}
    if re.search(r"\b(?:gst|tax)\b", text) and re.search(r"\b(?:paid|total|spend|expenditure)\b", text):
        return {"intent": "tax_total"}
    if re.search(r"\b(?:average|mean)\b", text) and re.search(r"\binvoice\b", text):
        return {"intent": "average_total"}
    if re.search(r"\b(?:above|over|greater than|more than)\b", text):
        match = re.search(r"(?:above|over|greater than|more than)\s*(?:₹|rs\.?\s*)?([\d,]+(?:\.\d{1,2})?)", text)
        if match:
            return {"intent": "amount_threshold", "amount": float(match.group(1).replace(",", ""))}
    if re.search(r"\b(?:invoice|bill)s?\b", text) and re.search(r"\b(?:from|for)\b", text):
        match = re.search(r"\b(?:from|for)\s+(.+?)(?:\s+(?:this|last|in|above|below)\b.*)?$", text)
        if match:
            vendor = match.group(1).strip(" .?!")
            if vendor:
                return {"intent": "vendor_invoices", "vendor": vendor[:120]}
    if re.search(r"\b(?:electronics|food|travel|utilities|logistics|grocery|drinks)\b", text) and re.search(r"\b(?:spend|spent|expenditure|how much)\b", text):
        category = re.search(r"\b(electronics|food|travel|utilities|logistics|grocery|drinks)\b", text)
        if category:
            return {"intent": "category_spend", "category": category.group(1)}
    if re.search(r"\b(?:total|spend|spent|expenditure)\b", text):
        period = "this_month" if re.search(r"\b(?:this month|month to date)\b", text) else (
            "last_month" if "last month" in text else "all"
        )
        return {"intent": "spend_total", "period": period}
    if "category" in context and re.search(r"\b(?:how much|spend|spent|total)\b", text):
        return {"intent": "category_spend", "category": context["category"]}
    return {"intent": "unknown"}


def _model_intent(question: str, history: list[dict]) -> dict:
    from backend.llm.mistral_service import (
        OLLAMA_HOST,
        OLLAMA_MODEL,
        OLLAMA_REQUEST_LOCK,
        _OLLAMA_SESSION,
        _ensure_model_available,
    )

    _ensure_model_available()
    schema = (
        "invoices(id,invoice_number,invoice_date,vendor_name,vendor_gstin,subtotal,"
        "total_tax,grand_total,validation_status,processing_status); "
        "invoice_items(invoice_id,description,amount,category); "
        "expense_categories(name)"
    )
    prompt = (
        "Map the question and recent conversation to one intent from this list: "
        + ", ".join(sorted(INTENTS))
        + ". Return one JSON object with intent, vendor, category, amount, limit, period. "
        "Never calculate or invent financial values. The actual SQLite schema is: "
        + schema
        + ". Conversation: "
        + json.dumps(history[-6:], ensure_ascii=False)[:2500]
        + ". Question: "
        + question[:500]
    )
    with OLLAMA_REQUEST_LOCK:
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
    if not isinstance(data, dict) or data.get("intent") not in INTENTS:
        return {"intent": "unknown"}
    result = {"intent": data["intent"]}
    for field in ("vendor", "category", "period"):
        value = data.get(field)
        if isinstance(value, str):
            result[field] = value[:120]
    if data.get("period") not in {"all", "this_month", "last_month"}:
        result["period"] = "all"
    if isinstance(data.get("amount"), (int, float)) and 0 <= data["amount"] <= 1_000_000_000:
        result["amount"] = float(data["amount"])
    if isinstance(data.get("limit"), int):
        result["limit"] = min(10, max(1, data["limit"]))
    return result


def _rows(db_path: str | Path, sql: str, parameters: tuple = ()) -> list[dict]:
    with db_connection(db_path) as connection:
        connection.set_progress_handler(lambda: 1, 500_000)
        cursor = connection.execute(sql, parameters)
        return [dict(row) for row in cursor.fetchmany(100)]


def answer_question(db_path: str | Path, question: str, history: list[dict] | None = None) -> dict:
    history = history if isinstance(history, list) else []
    intent = _deterministic_intent(question, history)
    model_warning = None
    if intent["intent"] == "unknown":
        try:
            intent = _model_intent(question, history)
        except (requests.RequestException, json.JSONDecodeError, RuntimeError, ValueError) as exc:
            intent = {"intent": "unknown"}
            model_warning = str(exc)

    name = intent["intent"]
    rows: list[dict] = []
    period = intent.get("period", "all")
    bounds = _period_bounds(period)
    context: dict = {}

    if name == "spend_total":
        where = " WHERE validation_status = 'Verified'"
        params: tuple = ()
        if bounds:
            where += " AND invoice_date >= ? AND invoice_date < ?"
            params = bounds
        rows = _rows(db_path, f"SELECT COALESCE(SUM(grand_total),0) AS total, COUNT(*) AS count FROM invoices{where}", params)
        period_label = {"this_month": "this month", "last_month": "last month"}.get(period, "all time")
        total = rows[0]["total"]
        answer = f"Verified expenditure for {period_label} is {_currency(total)} across {rows[0]['count']} invoices."
    elif name == "tax_total":
        rows = _rows(db_path, "SELECT COALESCE(SUM(total_tax),0) AS total FROM invoices WHERE validation_status='Verified'")
        answer = f"Recorded GST/tax paid on verified invoices is {_currency(rows[0]['total'])}."
    elif name == "average_total":
        rows = _rows(db_path, "SELECT COALESCE(AVG(grand_total),0) AS average, COUNT(*) AS count FROM invoices WHERE validation_status='Verified'")
        answer = f"The average verified invoice value is {_currency(rows[0]['average'])} across {rows[0]['count']} invoices."
    elif name == "vendor_top":
        rows = _rows(db_path, "SELECT vendor_name AS vendor, SUM(grand_total) AS amount, COUNT(*) AS invoice_count FROM invoices WHERE validation_status='Verified' AND vendor_name IS NOT NULL GROUP BY vendor_name ORDER BY amount DESC LIMIT 1")
        answer = f"{rows[0]['vendor']} is the highest-spending vendor at {_currency(rows[0]['amount'])}." if rows else "There are no verified invoices to compare vendors."
        if rows:
            context["vendor"] = rows[0]["vendor"]
    elif name == "vendor_frequency":
        rows = _rows(db_path, "SELECT vendor_name AS vendor, COUNT(*) AS invoice_count FROM invoices WHERE validation_status='Verified' AND vendor_name IS NOT NULL GROUP BY vendor_name ORDER BY invoice_count DESC LIMIT 1")
        answer = f"{rows[0]['vendor']} appears most often, with {rows[0]['invoice_count']} verified invoices." if rows else "There are no verified invoices to compare vendors."
        if rows:
            context["vendor"] = rows[0]["vendor"]
    elif name == "category_top":
        limit = intent.get("limit", 5)
        rows = _rows(db_path, "SELECT COALESCE(ii.category,'Other') AS category, SUM(COALESCE(ii.amount,0)) AS amount FROM invoice_items ii JOIN invoices i ON i.id=ii.invoice_id WHERE i.validation_status='Verified' GROUP BY COALESCE(ii.category,'Other') ORDER BY amount DESC LIMIT ?", (limit,))
        answer = "Top verified expense categories: " + (
            "; ".join(f"{row['category']} ({_currency(row['amount'])})" for row in rows)
            if rows else "no categorized expenses are recorded."
        )
    elif name == "monthly_top":
        rows = _rows(db_path, "SELECT substr(invoice_date,1,7) AS month, SUM(grand_total) AS amount FROM invoices WHERE validation_status='Verified' AND invoice_date IS NOT NULL GROUP BY substr(invoice_date,1,7) ORDER BY amount DESC LIMIT 1")
        answer = f"{rows[0]['month']} had the highest verified expenditure at {_currency(rows[0]['amount'])}." if rows else "There are no dated verified invoices to compare."
    elif name == "pending_invoices":
        rows = _rows(db_path, "SELECT invoice_number, vendor_name, invoice_date, grand_total, validation_status FROM invoices WHERE validation_status IS NULL OR validation_status != 'Verified' ORDER BY id DESC LIMIT 100")
        answer = f"Found {len(rows)} invoice(s) that are pending review or not verified." if rows else "There are no invoices awaiting review."
    elif name == "month_comparison":
        this_bounds = _period_bounds("this_month")
        last_bounds = _period_bounds("last_month")
        rows = _rows(db_path, "SELECT CASE WHEN invoice_date >= ? AND invoice_date < ? THEN 'this_month' ELSE 'last_month' END AS period, COALESCE(SUM(grand_total),0) AS amount FROM invoices WHERE validation_status='Verified' AND ((invoice_date >= ? AND invoice_date < ?) OR (invoice_date >= ? AND invoice_date < ?)) GROUP BY period", (*this_bounds, *this_bounds, *last_bounds))
        totals = {row["period"]: row["amount"] for row in rows}
        answer = f"This month: {_currency(totals.get('this_month',0))}; last month: {_currency(totals.get('last_month',0))}."
    elif name == "amount_threshold":
        amount = float(intent.get("amount", 0))
        rows = _rows(db_path, "SELECT invoice_number, vendor_name, invoice_date, grand_total, validation_status FROM invoices WHERE grand_total > ? ORDER BY grand_total DESC LIMIT 100", (amount,))
        answer = f"Found {len(rows)} invoice(s) above {_currency(amount)}."
    elif name == "vendor_invoices":
        vendor = str(intent.get("vendor") or "").strip()
        if not vendor:
            answer = "Which vendor should I look up?"
        else:
            rows = _rows(db_path, "SELECT invoice_number, vendor_name, invoice_date, grand_total, validation_status FROM invoices WHERE vendor_name LIKE ? ORDER BY invoice_date DESC LIMIT 100", (f"%{vendor}%",))
            answer = f"Found {len(rows)} invoice(s) for {vendor}."
            context["vendor"] = vendor
    elif name == "category_spend":
        category = str(intent.get("category") or "").strip()
        rows = _rows(db_path, "SELECT COALESCE(SUM(ii.amount),0) AS total, COUNT(DISTINCT i.id) AS invoice_count FROM invoice_items ii JOIN invoices i ON i.id=ii.invoice_id WHERE i.validation_status='Verified' AND (lower(COALESCE(ii.category,'')) LIKE ? OR lower(COALESCE(ii.description,'')) LIKE ?)", (f"%{category.lower()}%", f"%{category.lower()}%"))
        answer = f"Verified spending matching {category} is {_currency(rows[0]['total'])} across {rows[0]['invoice_count']} invoices."
        context["category"] = category
    else:
        answer = (
            "I couldn't map that question to a supported invoice query. Try asking about "
            "verified expenditure, tax, vendors, categories, invoice lists or monthly comparisons."
        )
        if model_warning:
            answer += f" The local model could not classify it: {model_warning}"

    return {"answer": answer, "rows": rows, "intent": name, "context": context}
