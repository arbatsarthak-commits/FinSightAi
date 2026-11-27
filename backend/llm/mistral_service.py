import json
import os
import re
import time
import requests
from pydantic import ValidationError

from config import OLLAMA_HOST, OLLAMA_MODEL
from backend.models.invoice import InvoiceData


EXTRACTION_PROMPT = """Extract invoice data from the OCR text below.
Return only a JSON object and use null for missing values. Do not invent values.
Use this structure:
{"invoice_number":null,"invoice_date":null,"due_date":null,"vendor_name":null,
"vendor_gstin":null,"customer_name":null,"customer_gstin":null,
"items":[{"description":null,"quantity":null,"unit_price":null,"discount":null,
"discount_percent":null,"taxable_value":null,"cgst":null,"sgst":null,
"igst":null,"amount":null,"category":"Other"}],
"subtotal":null,"cgst":null,"sgst":null,"igst":null,"total_tax":null,
"grand_total":null,"currency":"INR","payment_status":null}

Use discount for a fixed amount and discount_percent for a percentage.
Categories: food, logistics, drinks, travel, grocery expense, utilities, Other.

OCR TEXT:
{text}
"""

_OLLAMA_SESSION = requests.Session()

OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "2048"))
OLLAMA_NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "350"))
OLLAMA_NUM_THREAD = int(os.getenv("OLLAMA_NUM_THREAD", str(min(8, os.cpu_count() or 8))))
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "10m")
OCR_TEXT_LIMIT = int(os.getenv("OCR_TEXT_LIMIT", "6000"))


def _env_int(name: str, default: int, minimum: int) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except ValueError:
        return default


OLLAMA_NUM_CTX = _env_int("OLLAMA_NUM_CTX", 2048, 512)
OLLAMA_NUM_PREDICT = _env_int("OLLAMA_NUM_PREDICT", 350, 64)
OLLAMA_NUM_THREAD = _env_int("OLLAMA_NUM_THREAD", min(8, os.cpu_count() or 8), 1)
OCR_TEXT_LIMIT = _env_int("OCR_TEXT_LIMIT", 6000, 1000)


def _limit_ocr_text(raw_text: str, limit: int = OCR_TEXT_LIMIT) -> str:
    text = re.sub(r"[ \t]+", " ", raw_text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) <= limit:
        return text
    head_limit = max(limit * 2 // 3, 1)
    tail_limit = limit - head_limit
    head = text[:head_limit]
    tail = text[-tail_limit:] if tail_limit else ""
    return f"{head}\n...[text omitted]...\n{tail}"


def _extract_json(output: str) -> dict:
    output = re.sub(r"```(?:json)?", "", output, flags=re.IGNORECASE)
    start = output.find("{")
    if start < 0:
        raise ValueError("The model did not return a JSON object.")
    payload, _ = json.JSONDecoder().raw_decode(output[start:])
    if not isinstance(payload, dict):
        raise ValueError("The model did not return a JSON object.")
    return payload


def _number(value: str) -> float | None:
    cleaned = re.sub(r"[^\d.,]", "", value).replace(",", "")
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


def merge_deterministic_fields(raw_text: str, payload: dict) -> dict:
    """Fill only values that are unambiguous from common invoice labels."""
    text = raw_text.replace("\r", "\n")
    merged = dict(payload)

    if not merged.get("invoice_number"):
        match = re.search(
            r"\b(?:invoice|bill)\s*(?:number|no\.?|#)\s*[:\-]?\s*([A-Za-z0-9][A-Za-z0-9/_-]{2,30})",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            merged["invoice_number"] = match.group(1).strip()

    gstin_match = re.search(r"\b(?:GSTIN|GST\s*(?:IN|No\.?))\s*[:\-]?\s*([0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z][A-Z0-9])\b",
                           text, flags=re.IGNORECASE)
    if not merged.get("vendor_gstin") and gstin_match:
        merged["vendor_gstin"] = gstin_match.group(1).upper()

    for label, field in (
        ("grand total|invoice total|amount payable|total payable", "grand_total"),
        ("subtotal|taxable amount|taxable subtotal", "subtotal"),
        ("total tax|gst total|tax amount", "total_tax"),
    ):
        if merged.get(field) is not None:
            continue
        match = re.search(rf"(?im)^\s*(?:{label})\s*[:\-]?\s*(?:INR|Rs\.?|₹)?\s*([0-9][0-9,]*(?:\.[0-9]{{1,2}})?)",
                          text)
        if match:
            merged[field] = _number(match.group(1))

    if not merged.get("vendor_name"):
        match = re.search(r"(?im)^\s*(?:from|vendor|billed by)\s*[:\-]\s*(.+)$", text)
        if match:
            candidate = re.sub(r"\s{2,}", " ", match.group(1)).strip(" :-")
            if candidate:
                merged["vendor_name"] = candidate[:120]

    return merged


def extract_invoice_with_metrics(raw_text: str, retries: int = 1) -> tuple[InvoiceData, dict]:
    inference_seconds = 0.0
    validation_seconds = 0.0
    server_metrics = {
        "ollama_total_seconds": 0.0,
        "ollama_load_seconds": 0.0,
        "ollama_prompt_eval_seconds": 0.0,
        "ollama_generation_seconds": 0.0,
        "ollama_prompt_tokens": 0,
        "ollama_generated_tokens": 0,
    }
    last_error = None
    for _ in range(retries + 1):
        try:
            started = time.perf_counter()
            limited_text = _limit_ocr_text(raw_text)
            response = _OLLAMA_SESSION.post(
                f"{OLLAMA_HOST.rstrip('/')}/api/generate",
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": EXTRACTION_PROMPT.replace("{text}", limited_text),
                    "stream": False,
                    "format": "json",
                    "keep_alive": OLLAMA_KEEP_ALIVE,
                    "options": {
                        "temperature": 0,
                        "num_ctx": OLLAMA_NUM_CTX,
                        "num_predict": OLLAMA_NUM_PREDICT,
                        "num_thread": OLLAMA_NUM_THREAD,
                    },
                },
                timeout=(10, 300),
            )
            response.raise_for_status()
            inference_seconds += time.perf_counter() - started
            response_body = response.json()
            if not isinstance(response_body, dict) or not isinstance(
                response_body.get("response"), str
            ):
                raise ValueError("The model returned an invalid response.")
            if response_body.get("done_reason") == "length":
                raise ValueError("The model output was truncated.")
            for key, source_key in (
                ("ollama_total_seconds", "total_duration"),
                ("ollama_load_seconds", "load_duration"),
                ("ollama_prompt_eval_seconds", "prompt_eval_duration"),
                ("ollama_generation_seconds", "eval_duration"),
            ):
                if isinstance(response_body.get(source_key), (int, float)):
                    server_metrics[key] += response_body[source_key] / 1_000_000_000
            for key, source_key in (
                ("ollama_prompt_tokens", "prompt_eval_count"),
                ("ollama_generated_tokens", "eval_count"),
            ):
                if isinstance(response_body.get(source_key), int):
                    server_metrics[key] += response_body[source_key]
            payload = merge_deterministic_fields(limited_text, _extract_json(response_body["response"]))
            started = time.perf_counter()
            invoice = InvoiceData.model_validate(payload)
            validation_seconds += time.perf_counter() - started
            return invoice, {
                "mistral_inference_seconds": round(inference_seconds, 4),
                "pydantic_validation_seconds": round(validation_seconds, 4),
                "ollama_tokens_per_second": round(
                    server_metrics["ollama_generated_tokens"]
                    / max(server_metrics["ollama_generation_seconds"], 1e-9),
                    2,
                ),
                **{
                    key: round(value, 4) if key.endswith("_seconds") else value
                    for key, value in server_metrics.items()
                },
            }
        except requests.RequestException as exc:
            raise RuntimeError(f"Invoice extraction request failed: {exc}") from exc
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            last_error = exc
    raise RuntimeError(f"Invoice extraction returned invalid data after retries: {last_error}")


def extract_invoice(raw_text: str, retries: int = 2) -> InvoiceData:
    invoice, _ = extract_invoice_with_metrics(raw_text, retries=retries)
    return invoice


def ollama_status() -> dict:
    try:
        response = requests.get(f"{OLLAMA_HOST.rstrip('/')}/api/tags", timeout=5)
        response.raise_for_status()
        model_entries = response.json().get("models", [])
        models = [
            model.get("name", "")
            for model in model_entries
            if isinstance(model, dict)
        ]
        loaded = []
        processor_usage = "not reported"
        try:
            running = requests.get(f"{OLLAMA_HOST.rstrip('/')}/api/ps", timeout=3)
            if running.ok:
                loaded_entries = running.json().get("models", [])
                loaded = [model.get("name", "") for model in loaded_entries if isinstance(model, dict)]
                any_gpu = any(
                    int(model.get("size_vram", 0) or 0) > 0
                    for model in loaded_entries
                    if isinstance(model, dict)
                )
                processor_usage = "GPU/CPU hybrid" if any_gpu else "CPU"
        except requests.RequestException:
            pass
        return {
            "reachable": True,
            "models": models,
            "selected_model_available": any(
                name == OLLAMA_MODEL or name.startswith(f"{OLLAMA_MODEL}:")
                for name in models
            ),
            "loaded_models": loaded,
            "processor_usage": processor_usage,
            "cpu_threads": OLLAMA_NUM_THREAD,
            "context_window": OLLAMA_NUM_CTX,
            "max_generated_tokens": OLLAMA_NUM_PREDICT,
            "logical_processors": os.cpu_count() or 1,
        }
    except requests.RequestException as exc:
        return {"reachable": False, "models": [], "selected_model_available": False, "error": str(exc)}
