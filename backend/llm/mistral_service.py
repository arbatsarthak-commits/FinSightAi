import json
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


def _limit_ocr_text(raw_text: str, limit: int = 12000) -> str:
    text = re.sub(r"[ \t]+", " ", raw_text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) <= limit:
        return text
    head = text[:8000]
    tail = text[-4000:]
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
                    "keep_alive": "30m",
                    "options": {
                        "temperature": 0,
                        "num_ctx": 4096,
                        "num_predict": 700,
                        "num_thread": 8,
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
            payload = _extract_json(response_body["response"])
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
        models = [
            model.get("name", "")
            for model in response.json().get("models", [])
            if isinstance(model, dict)
        ]
        return {
            "reachable": True,
            "models": models,
            "selected_model_available": any(
                name == OLLAMA_MODEL or name.startswith(f"{OLLAMA_MODEL}:")
                for name in models
            ),
        }
    except requests.RequestException as exc:
        return {"reachable": False, "models": [], "selected_model_available": False, "error": str(exc)}
