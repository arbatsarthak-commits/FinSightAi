import os
import shutil
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent


def _load_local_env() -> None:
    env_file = BASE_DIR / ".env"
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        entry = line.strip()
        if not entry or entry.startswith("#") or "=" not in entry:
            continue
        key, value = entry.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and key.replace("_", "").isalnum():
            os.environ.setdefault(key, value)


_load_local_env()
DB_PATH = Path(os.getenv("INVOICE_DB_PATH", BASE_DIR / "ocr_master_table.db"))


def _tesseract_default() -> str:
    configured = os.getenv("TESSERACT_CMD")
    if configured:
        return configured
    on_path = shutil.which("tesseract")
    if on_path:
        return on_path
    for root in (os.getenv("ProgramFiles"), os.getenv("ProgramFiles(x86)")):
        if root:
            candidate = Path(root) / "Tesseract-OCR" / "tesseract.exe"
            if candidate.is_file():
                return str(candidate)
    return r"C:\Program Files\Tesseract-OCR\tesseract.exe"


TESSERACT_CMD = _tesseract_default()
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:1.5b")
LAYOUTLM_MODEL = os.getenv("LAYOUTLM_MODEL", "")
OCR_TIMEOUT_SECONDS = max(1, int(os.getenv("OCR_TIMEOUT_SECONDS", "25")))
MAX_IMAGE_PIXELS = max(1, int(os.getenv("MAX_IMAGE_PIXELS", "40000000")))
MAX_PDF_PAGES = max(1, int(os.getenv("MAX_PDF_PAGES", "30")))
