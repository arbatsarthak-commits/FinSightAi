import os
import threading
import time

os.environ["LOCAL_API_TOKEN"] = "test-pairing-token-that-is-at-least-32-chars"

import pytest
from fastapi.testclient import TestClient

from backend import main
from backend.database.database import initialize_database, save_extracted_invoice


client = TestClient(main.app)
HEADERS = {"X-Pairing-Token": os.environ["LOCAL_API_TOKEN"]}


def test_health_endpoint():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_system_status_endpoint():
    response = client.get("/api/system/status", headers=HEADERS)
    assert response.status_code == 200
    assert "backend" in response.json()


def test_rejects_unsupported_upload():
    response = client.post(
        "/api/invoices/upload",
        files={"file": ("invoice.txt", b"not an invoice", "text/plain")},
        headers=HEADERS,
    )
    assert response.status_code == 415


def test_overview_endpoint():
    response = client.get("/api/analytics/overview", headers=HEADERS)
    assert response.status_code == 200
    assert "summary" in response.json()


def test_private_endpoints_require_pairing():
    for path in (
        "/api/system/status",
        "/api/invoices",
        "/api/invoices/upload/not-a-real-file",
        "/api/processing/unknown-job",
        "/api/analytics/overview",
        "/api/analytics/monthly",
        "/api/analytics/categories",
        "/api/analytics/vendors",
        "/api/reports/export",
    ):
        assert client.get(path).status_code == 401


def test_github_pages_origin_is_allowed_for_local_backend():
    response = client.options(
        "/api/invoices/upload",
        headers={
            "Origin": "https://arbatsarthak-commits.github.io",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-pairing-token",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == (
        "https://arbatsarthak-commits.github.io"
    )
    allowed_headers = response.headers["access-control-allow-headers"].lower()
    assert "content-type" in allowed_headers
    assert "x-pairing-token" in allowed_headers
    assert "post" in response.headers["access-control-allow-methods"].lower()


def test_manual_approval_and_edit_routes_are_removed():
    assert client.post("/api/invoices/1/approve", headers=HEADERS).status_code == 404
    assert client.put("/api/invoices/1", headers=HEADERS, json={}).status_code == 405


def test_analyze_returns_real_job_progress_and_auto_saved_result(tmp_path, monkeypatch):
    data_dir = tmp_path / "uploads"
    data_dir.mkdir()
    monkeypatch.setattr(main, "DATA_DIR", data_dir)
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "processing-job.db")
    initialize_database(main.DB_PATH)

    def fake_process(source, stage_callback, upload_seconds):
        stage_callback("File validation", "Processing", None)
        stage_callback("File validation", "Complete", None)
        invoice_id = save_extracted_invoice(
            main.DB_PATH,
            {"invoice_number": "INV-JOB", "items": []},
            source.name,
            {"status": "Verified"},
            "{}",
            processing_status="Processed",
            source_hash="job-source-hash",
        )
        return {
            "invoice_id": invoice_id,
            "processing_status": "Processed",
            "auto_saved": True,
            "performance": {"upload_seconds": upload_seconds},
        }

    monkeypatch.setattr(main, "process_invoice", fake_process)
    uploaded = client.post(
        "/api/invoices/upload",
        files={"file": ("invoice.png", b"invoice bytes", "image/png")},
        headers=HEADERS,
    )
    assert uploaded.status_code == 200
    queued = client.post(
        f"/api/invoices/{uploaded.json()['upload_id']}/analyze", headers=HEADERS
    )
    assert queued.status_code == 202

    for _ in range(50):
        status = client.get(
            f"/api/processing/{queued.json()['job_id']}", headers=HEADERS
        ).json()
        if status["status"] in {"complete", "failed"}:
            break
        time.sleep(0.02)

    assert status["status"] == "complete"
    assert status["stages"]["File validation"]["status"] == "Complete"
    assert status["result"]["auto_saved"] is True
    assert status["result"]["performance"]["upload_seconds"] >= 0


def test_identical_uploads_share_one_active_processing_job(tmp_path, monkeypatch):
    data_dir = tmp_path / "uploads"
    data_dir.mkdir()
    monkeypatch.setattr(main, "DATA_DIR", data_dir)
    monkeypatch.setattr(main, "_processing_jobs", {})
    monkeypatch.setattr(main, "_active_upload_jobs", {})
    monkeypatch.setattr(main, "_active_upload_hashes", {})
    started = threading.Event()
    release = threading.Event()

    def fake_process(source, stage_callback, upload_seconds):
        started.set()
        assert release.wait(timeout=5)
        return {"duplicate": False, "auto_saved": True}

    monkeypatch.setattr(main, "process_invoice", fake_process)
    try:
        first_upload = client.post(
            "/api/invoices/upload",
            files={"file": ("invoice.png", b"same invoice content", "image/png")},
            headers=HEADERS,
        )
        first_job = client.post(
            f"/api/invoices/{first_upload.json()['upload_id']}/analyze",
            headers=HEADERS,
        )
        assert started.wait(timeout=2)

        second_upload = client.post(
            "/api/invoices/upload",
            files={"file": ("invoice-copy.png", b"same invoice content", "image/png")},
            headers=HEADERS,
        )
        second_job = client.post(
            f"/api/invoices/{second_upload.json()['upload_id']}/analyze",
            headers=HEADERS,
        )

        assert first_job.status_code == second_job.status_code == 202
        assert first_job.json()["job_id"] == second_job.json()["job_id"]
    finally:
        release.set()
        job_id = first_job.json()["job_id"] if "first_job" in locals() else None
        for _ in range(100):
            if job_id and main._processing_jobs.get(job_id, {}).get("status") == "complete":
                break
            time.sleep(0.01)


def test_csv_formula_injection_is_neutralized():
    assert main.csv_safe("=HYPERLINK(\"https://example.invalid\")").startswith("'=")
    assert main.csv_safe("  @SUM(A1:A2)").startswith("'")
    assert main.csv_safe("Acme Ltd") == "Acme Ltd"


def test_csv_export_requires_auth_and_neutralizes_formulas(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "csv.db")
    initialize_database(main.DB_PATH)
    save_extracted_invoice(
        main.DB_PATH,
        {
            "invoice_number": "=1+1",
            "invoice_date": "2026-11-23",
            "vendor_name": "+Formula Vendor",
            "grand_total": 10,
            "items": [],
        },
        "csv.png",
        {"status": "Needs Attention"},
        "{}",
    )
    assert client.get("/api/reports/export").status_code == 401
    response = client.get("/api/reports/export", headers=HEADERS)
    assert response.status_code == 200
    assert "'=1+1" in response.text
    assert "'+Formula Vendor" in response.text


def test_private_preview_requires_auth():
    assert client.get("/api/invoices/upload/test.png").status_code == 401


def test_missing_pairing_configuration_fails_startup(monkeypatch):
    monkeypatch.setattr(main, "PAIRING_TOKEN", "")
    with pytest.raises(RuntimeError, match="LOCAL_API_TOKEN"):
        with TestClient(main.app):
            pass


def test_delete_route_is_removed_and_record_is_preserved(tmp_path, monkeypatch):
    data_dir = tmp_path / "uploads"
    data_dir.mkdir()
    monkeypatch.setattr(main, "DATA_DIR", data_dir)
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "deletion.db")
    initialize_database(main.DB_PATH)
    uploaded_file = data_dir / "stored.png"
    uploaded_file.write_bytes(b"invoice bytes")
    invoice_id = save_extracted_invoice(
        main.DB_PATH,
        {"invoice_number": "INV-DELETE", "items": []},
        uploaded_file.name,
        {"status": "Needs Attention"},
        "{}",
        source_hash="delete-hash",
    )
    details = client.get(f"/api/invoices/{invoice_id}", headers=HEADERS)
    assert details.status_code == 200
    assert "approval_status" not in details.json()["invoice"]

    response = client.delete(f"/api/invoices/{invoice_id}", headers=HEADERS)

    assert response.status_code == 405
    assert uploaded_file.exists()
    assert main.get_invoice_details(main.DB_PATH, invoice_id)
