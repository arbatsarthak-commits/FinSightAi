import tempfile
from pathlib import Path

import cv2
import numpy as np
import pytest

from backend.preprocessing.image_processor import preprocess_image
from backend.ocr import ocr_service
from backend.ocr.ocr_service import RenderedPagePaths, extract_document, pdf_to_images


def test_preprocess_image(tmp_path):
    image_path = tmp_path / "invoice.png"
    cv2.imwrite(str(image_path), np.full((400, 600, 3), 245, dtype=np.uint8))
    processed = preprocess_image(image_path)
    assert processed.shape == (400, 600)


def test_blank_image_is_rejected(tmp_path):
    image_path = tmp_path / "blank.png"
    cv2.imwrite(str(image_path), np.full((400, 600, 3), 255, dtype=np.uint8))
    with pytest.raises(ValueError, match="No readable text"):
        extract_document(image_path)


def test_pdf_conversion_does_not_stop_at_ten_pages(tmp_path):
    fitz = pytest.importorskip("fitz")
    pdf_path = tmp_path / "multipage.pdf"
    document = fitz.open()
    for _ in range(11):
        document.new_page(width=100, height=100)
    document.save(pdf_path)
    document.close()

    rendered = pdf_to_images(pdf_path, tmp_path / "pages")

    assert len(rendered) == 11
    assert rendered.total_pages == 11
    assert rendered.limit_reason is None


def test_ocr_uses_one_tesseract_pass_and_reconstructs_lines(tmp_path, monkeypatch):
    image_path = tmp_path / "invoice.png"
    image = np.full((200, 300, 3), 255, dtype=np.uint8)
    cv2.rectangle(image, (20, 20), (200, 80), (0, 0, 0), -1)
    cv2.imwrite(str(image_path), image)
    calls = []

    def fake_image_to_data(*args, **kwargs):
        calls.append("data")
        return {
            "text": ["Invoice", "123", ""],
            "conf": ["90", "95", "-1"],
            "left": [10, 100, 0],
            "top": [10, 10, 0],
            "width": [70, 30, 0],
            "height": [20, 20, 0],
            "block_num": [1, 1, 0],
            "par_num": [1, 1, 0],
            "line_num": [1, 1, 0],
        }

    monkeypatch.setattr(ocr_service, "check_tesseract", lambda: "5.5")
    monkeypatch.setattr(ocr_service.pytesseract, "image_to_data", fake_image_to_data)
    monkeypatch.setattr(
        ocr_service.pytesseract,
        "image_to_string",
        lambda *args, **kwargs: pytest.fail("A second OCR pass should not run."),
    )

    result = extract_document(image_path)

    assert calls == ["data"]
    assert result["text"] == "Invoice 123"
    assert result["pages"][0]["average_confidence"] == 92.5
    assert "preprocessing_seconds" in result["performance"]


def test_pdf_page_images_are_cleaned_after_extraction(tmp_path, monkeypatch):
    pdf_path = tmp_path / "invoice.pdf"
    pdf_path.write_bytes(b"test pdf")

    def fake_pdf_to_images(source, output_dir, max_pages):
        image_path = Path(output_dir) / "page_1.png"
        image = np.full((200, 300, 3), 255, dtype=np.uint8)
        cv2.rectangle(image, (20, 20), (200, 80), (0, 0, 0), -1)
        cv2.imwrite(str(image_path), image)
        return [image_path]

    monkeypatch.setattr(ocr_service, "check_tesseract", lambda: "5.5")
    monkeypatch.setattr(ocr_service, "pdf_to_images", fake_pdf_to_images)
    monkeypatch.setattr(
        ocr_service.pytesseract,
        "image_to_data",
        lambda *args, **kwargs: {
            "text": ["Invoice"],
            "conf": ["90"],
            "left": [10],
            "top": [10],
            "width": [70],
            "height": [20],
            "block_num": [1],
            "par_num": [1],
            "line_num": [1],
        },
    )
    existing_temp_dirs = set(Path(tempfile.gettempdir()).glob("invoice_pages_*"))

    result = extract_document(pdf_path)

    assert result["text"] == "Invoice"
    assert result["document"]["pages_total"] == 1
    assert result["document"]["partial"] is False
    assert set(Path(tempfile.gettempdir()).glob("invoice_pages_*")) == existing_temp_dirs


def test_pdf_page_limit_is_reported_as_partial(tmp_path, monkeypatch):
    pdf_path = tmp_path / "long-invoice.pdf"
    pdf_path.write_bytes(b"test pdf")
    conversions = []

    def fake_pdf_to_images(source, output_dir, max_pages):
        conversions.append(max_pages)
        image_path = Path(output_dir) / "page_1.png"
        image = np.full((200, 300, 3), 255, dtype=np.uint8)
        cv2.rectangle(image, (20, 20), (200, 80), (0, 0, 0), -1)
        cv2.imwrite(str(image_path), image)
        return RenderedPagePaths([image_path], total_pages=12)

    monkeypatch.setattr(ocr_service, "check_tesseract", lambda: "5.5")
    monkeypatch.setattr(ocr_service, "pdf_to_images", fake_pdf_to_images)
    monkeypatch.setattr(
        ocr_service.pytesseract,
        "image_to_data",
        lambda *args, **kwargs: {
            "text": ["Invoice"], "conf": ["90"], "left": [10], "top": [10],
            "width": [70], "height": [20], "block_num": [1], "par_num": [1],
            "line_num": [1],
        },
    )

    result = extract_document(pdf_path, max_pages=1)

    assert result["document"]["pages_total"] == 12
    assert result["document"]["pages_processed"] == 1
    assert result["document"]["partial"] is True
    assert "first 1 of 12" in result["document"]["warning"]
    extract_document(pdf_path, max_pages=12)
    assert conversions == [1, 12]
