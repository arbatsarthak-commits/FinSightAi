import copy
import pytesseract
import cv2
import hashlib
import re
from pathlib import Path
import tempfile
import time
from functools import lru_cache
from typing import Callable
from PIL import Image, UnidentifiedImageError

from config import MAX_IMAGE_PIXELS, MAX_PDF_PAGES, OCR_TIMEOUT_SECONDS, TESSERACT_CMD
from backend.preprocessing.image_processor import preprocess_image, SUPPORTED_IMAGE_EXTENSIONS

_OCR_CACHE: dict[tuple[str, str, int], dict] = {}
MAX_PDF_PAGE_PIXELS = 12_000_000
MAX_PDF_TOTAL_PIXELS = 60_000_000


def _ocr_quality_score(data: dict) -> float:
    confidences = [
        float(value)
        for value in data.get("conf", [])
        if str(value).strip() and float(value) >= 0
    ]
    average_confidence = sum(confidences) / len(confidences) if confidences else 0.0
    grouped_lines: dict[tuple[int, int, int], list[str]] = {}
    texts = data.get("text", [])
    for index, value in enumerate(texts):
        text = str(value).strip()
        if not text:
            continue
        key = (
            int(data.get("block_num", [0] * len(texts))[index]),
            int(data.get("par_num", [0] * len(texts))[index]),
            int(data.get("line_num", [index] * len(texts))[index]),
        )
        grouped_lines.setdefault(key, []).append(text)
    lines = [" ".join(words) for words in grouped_lines.values()]
    score = average_confidence
    score += 5 * sum(
        bool(
            re.search(
                r"\b(?:sub\s*total|grand\s*total|total|cgst|sgst|igst)\b.*\d",
                line,
                re.IGNORECASE,
            )
        )
        for line in lines
    )
    score += 3 * sum(
        bool(re.search(r"[A-Za-z]", line))
        and len(re.findall(r"\d+(?:[.,]\d+)?", line)) >= 2
        for line in lines
    )
    score += 3 * sum(
        bool(re.search(r"\b(?:invoice|bill)\b.*\d", line, re.IGNORECASE))
        for line in lines
    )
    score += 3 * sum(
        bool(re.search(r"\bdate\b.*\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", line, re.IGNORECASE))
        for line in lines
    )
    return score


class RenderedPagePaths(list[Path]):
    def __init__(
        self,
        paths: list[Path],
        total_pages: int,
        limit_reason: str | None = None,
    ):
        super().__init__(paths)
        self.total_pages = total_pages
        self.limit_reason = limit_reason

pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD


def validate_document_file(source: str | Path) -> None:
    source = Path(source)
    suffix = source.suffix.lower()
    if suffix == ".pdf":
        with source.open("rb") as handle:
            if not handle.read(1024).lstrip().startswith(b"%PDF-"):
                raise ValueError("The uploaded file is not a valid PDF.")
        return
    expected_formats = {".jpg": {"JPEG"}, ".jpeg": {"JPEG"}, ".png": {"PNG"}}
    if suffix not in expected_formats:
        raise ValueError("Unsupported file type. Use JPG, JPEG, PNG or PDF.")
    try:
        with Image.open(source) as image:
            width, height = image.size
            if width < 1 or height < 1 or width * height > MAX_IMAGE_PIXELS:
                raise ValueError(
                    f"Image dimensions exceed the {MAX_IMAGE_PIXELS:,}-pixel safety limit."
                )
            if image.format not in expected_formats[suffix]:
                raise ValueError("The image content does not match its file extension.")
            image.verify()
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("The image is corrupted or cannot be decoded.") from exc


@lru_cache(maxsize=1)
def check_tesseract() -> str:
    configured = Path(TESSERACT_CMD)
    if not configured.is_file():
        raise RuntimeError(
            f"Tesseract executable was not found at {configured}. "
            "Set TESSERACT_CMD to the installed tesseract.exe path."
        )
    try:
        version = pytesseract.get_tesseract_version()
        return str(version)
    except Exception as exc:
        raise RuntimeError(f"Tesseract could not be started: {exc}") from exc


def pdf_to_images(
    pdf_path: str | Path,
    output_dir: str | Path,
    max_pages: int = MAX_PDF_PAGES,
) -> RenderedPagePaths:
    if max_pages < 1:
        raise ValueError("The PDF page limit must be at least one.")
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PDF support requires the pymupdf package.") from exc

    try:
        document = fitz.open(str(pdf_path))
    except Exception as exc:
        raise ValueError(f"The PDF could not be opened: {exc}") from exc
    images = []
    total_pages = document.page_count
    rendered_pixels = 0
    limit_reason = None
    try:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        for page_number in range(min(total_pages, max_pages)):
            try:
                page = document.load_page(page_number)
                page_area = max(1.0, page.rect.width * page.rect.height)
                remaining_pixels = MAX_PDF_TOTAL_PIXELS - rendered_pixels
                if remaining_pixels <= 0 and images:
                    limit_reason = (
                        f"the {MAX_PDF_TOTAL_PIXELS:,}-pixel total rendering limit"
                    )
                    break
                scale = min(
                    2.0,
                    (min(MAX_PDF_PAGE_PIXELS, remaining_pixels) / page_area) ** 0.5,
                )
                pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                image_path = output_dir / f"page_{page_number + 1}.png"
                pixmap.save(str(image_path))
                images.append(image_path)
                rendered_pixels += pixmap.width * pixmap.height
                del pixmap
            except Exception as exc:
                raise ValueError(f"PDF page {page_number + 1} could not be rendered: {exc}") from exc
        if total_pages > len(images) and limit_reason is None:
            if len(images) >= max_pages:
                limit_reason = f"the {max_pages}-page processing limit"
    finally:
        document.close()
    return RenderedPagePaths(images, total_pages, limit_reason)


def extract_document(
    source: str | Path,
    max_pages: int = MAX_PDF_PAGES,
    on_stage: Callable[[str, str, str | None], None] | None = None,
) -> dict:
    check_tesseract()
    source = Path(source)
    if not source.exists():
        raise FileNotFoundError(f"Invoice file not found: {source}")
    suffix = source.suffix.lower()
    validate_document_file(source)
    pdf_conversion_seconds = 0.0
    temporary_directory = None
    total_pages = 1
    cache_lookup_started = time.perf_counter()
    cache_key = (
        str(source.resolve()),
        hashlib.sha256(source.read_bytes()).hexdigest(),
        max_pages,
    )
    cache_lookup_seconds = time.perf_counter() - cache_lookup_started
    cached = _OCR_CACHE.get(cache_key)
    if cached is not None:
        result = copy.deepcopy(cached)
        result["performance"] = {
            "pdf_conversion_seconds": 0.0,
            "preprocessing_seconds": 0.0,
            "ocr_seconds": 0.0,
            "ocr_cache_hit": True,
            "ocr_cache_lookup_seconds": round(cache_lookup_seconds, 4),
        }
        return result
    if suffix == ".pdf":
        temporary_directory = tempfile.TemporaryDirectory(prefix="invoice_pages_")
        started = time.perf_counter()
        if on_stage:
            on_stage("PDF conversion", "Processing", None)
        try:
            page_paths = pdf_to_images(source, temporary_directory.name, max_pages)
        except Exception:
            temporary_directory.cleanup()
            raise
        pdf_conversion_seconds = time.perf_counter() - started
        total_pages = getattr(page_paths, "total_pages", len(page_paths))
        page_limit_reason = getattr(page_paths, "limit_reason", None)
        page_count_detail = (
            f"Processed {len(page_paths)} of {total_pages} pages; "
            f"stopped at {page_limit_reason or f'the {max_pages}-page processing limit'}."
            if len(page_paths) < total_pages
            else f"Processed all {total_pages} pages."
        )
        if on_stage:
            on_stage("PDF conversion", "Complete", page_count_detail)
    elif suffix in SUPPORTED_IMAGE_EXTENSIONS:
        page_paths = [source]
    else:
        raise ValueError("Unsupported file type. Use JPG, JPEG, PNG or PDF.")
    if not page_paths:
        if temporary_directory:
            temporary_directory.cleanup()
        raise ValueError("The document contains no readable pages.")

    page_results = []
    all_text = []
    all_words = []
    preprocessing_seconds = 0.0
    ocr_seconds = 0.0
    try:
        for page_number, page_path in enumerate(page_paths, start=1):
            if on_stage:
                on_stage("OpenCV preprocessing", "Processing", f"Page {page_number}")
            started = time.perf_counter()
            processed = preprocess_image(page_path)
            preprocessing_seconds += time.perf_counter() - started
            if on_stage:
                on_stage("OpenCV preprocessing", "Complete", f"Page {page_number}")
            words = []
            lines = {}
            if cv2.countNonZero(255 - processed) >= 10:
                if on_stage:
                    on_stage("Tesseract OCR", "Processing", f"Page {page_number}")
                started = time.perf_counter()
                try:
                    data = pytesseract.image_to_data(
                        processed, config="--psm 6", output_type=pytesseract.Output.DICT,
                        timeout=OCR_TIMEOUT_SECONDS,
                    )
                except pytesseract.TesseractError as exc:
                    raise RuntimeError(f"OCR failed on page {page_number}: {exc}") from exc
                except RuntimeError as exc:
                    raise TimeoutError(
                        f"OCR timed out on page {page_number} after {OCR_TIMEOUT_SECONDS} seconds."
                    ) from exc
                selected_data = data
                selected_score = _ocr_quality_score(data)
                confidences = [
                    float(value)
                    for value in data["conf"]
                    if str(value).strip() and float(value) >= 0
                ]
                average_confidence = (
                    sum(confidences) / len(confidences) if confidences else 0.0
                )
                if average_confidence < 65:
                    if on_stage:
                        on_stage(
                            "OpenCV preprocessing", "Processing",
                            f"Adaptive fallback for page {page_number}",
                        )
                    preprocessing_started = time.perf_counter()
                    adaptive = preprocess_image(page_path, adaptive=True)
                    preprocessing_seconds += time.perf_counter() - preprocessing_started
                    if on_stage:
                        on_stage("OpenCV preprocessing", "Complete", f"Page {page_number}")
                    try:
                        adaptive_data = pytesseract.image_to_data(
                            adaptive,
                            config="--psm 6",
                            output_type=pytesseract.Output.DICT,
                            timeout=OCR_TIMEOUT_SECONDS,
                        )
                    except pytesseract.TesseractError as exc:
                        raise RuntimeError(
                            f"Adaptive OCR failed on page {page_number}: {exc}"
                        ) from exc
                    except RuntimeError as exc:
                        raise TimeoutError(
                            f"Adaptive OCR timed out on page {page_number} after "
                            f"{OCR_TIMEOUT_SECONDS} seconds."
                        ) from exc
                    adaptive_score = _ocr_quality_score(adaptive_data)
                    if adaptive_score > selected_score:
                        selected_data = adaptive_data
                        selected_score = adaptive_score
                        processed = adaptive
                selected_confidences = [
                    float(value)
                    for value in selected_data["conf"]
                    if str(value).strip() and float(value) >= 0
                ]
                selected_average = (
                    sum(selected_confidences) / len(selected_confidences)
                    if selected_confidences else 0.0
                )
                if selected_average < 45:
                    try:
                        sparse_data = pytesseract.image_to_data(
                            processed,
                            config="--psm 11",
                            output_type=pytesseract.Output.DICT,
                            timeout=OCR_TIMEOUT_SECONDS,
                        )
                    except pytesseract.TesseractError as exc:
                        raise RuntimeError(
                            f"Sparse OCR fallback failed on page {page_number}: {exc}"
                        ) from exc
                    except RuntimeError as exc:
                        raise TimeoutError(
                            f"Sparse OCR fallback timed out on page {page_number} after "
                            f"{OCR_TIMEOUT_SECONDS} seconds."
                        ) from exc
                    if _ocr_quality_score(sparse_data) > selected_score:
                        selected_data = sparse_data
                data = selected_data
                ocr_seconds += time.perf_counter() - started
                if on_stage:
                    on_stage("Tesseract OCR", "Complete", f"Page {page_number}")

                for index, text in enumerate(data["text"]):
                    text = text.strip()
                    if not text:
                        continue
                    try:
                        confidence = float(data["conf"][index])
                    except (TypeError, ValueError):
                        confidence = -1.0
                    words.append({
                        "text": text,
                        "confidence": confidence,
                        "left": int(data["left"][index]),
                        "top": int(data["top"][index]),
                        "width": int(data["width"][index]),
                        "height": int(data["height"][index]),
                        "block_num": int(data.get("block_num", [0] * len(data["text"]))[index]),
                        "par_num": int(data.get("par_num", [0] * len(data["text"]))[index]),
                        "line_num": int(data.get("line_num", [index] * len(data["text"]))[index]),
                        "page": page_number,
                    })
                    line_key = (
                        int(data["block_num"][index]),
                        int(data["par_num"][index]),
                        int(data["line_num"][index]),
                    )
                    lines.setdefault(line_key, []).append(text)
            page_text = "\n".join(" ".join(line) for line in lines.values()).strip()
            all_text.append(page_text)
            all_words.extend(words)
            confidences = [word["confidence"] for word in words if word["confidence"] >= 0]
            page_results.append({
                "page": page_number,
                "text": page_text,
                "word_count": len(words),
                "average_confidence": round(sum(confidences) / max(1, len(confidences)), 2),
            })
    finally:
        if temporary_directory:
            temporary_directory.cleanup()

    combined_text = "\n\n".join(all_text).strip()
    if not combined_text:
        raise ValueError(
            "No readable text was detected. Try a clearer, brighter, or correctly rotated invoice."
        )

    result = {
        "source": source.name,
        "text": combined_text,
        "pages": page_results,
        "document": {
            "pages_total": total_pages,
            "pages_processed": len(page_paths),
            "partial": len(page_paths) < total_pages,
            "warning": (
                f"Only the first {len(page_paths)} of {total_pages} PDF pages were processed "
                f"because processing reached {page_limit_reason or f'the {max_pages}-page limit'}."
                if len(page_paths) < total_pages
                else None
            ),
        },
        "words": all_words,
        "performance": {
            "pdf_conversion_seconds": round(pdf_conversion_seconds, 4),
            "preprocessing_seconds": round(preprocessing_seconds, 4),
            "ocr_seconds": round(ocr_seconds, 4),
            "ocr_cache_hit": False,
            "ocr_cache_lookup_seconds": round(cache_lookup_seconds, 4),
        },
    }
    if len(_OCR_CACHE) >= 16:
        _OCR_CACHE.pop(next(iter(_OCR_CACHE)))
    _OCR_CACHE[cache_key] = result
    return result
