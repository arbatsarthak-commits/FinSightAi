from unittest.mock import patch

from backend.llm.mistral_service import _limit_ocr_text, extract_invoice


def test_ocr_prompt_compaction_preserves_invoice_line_breaks():
    assert _limit_ocr_text("Invoice 123\nVendor: Example\n\nTotal: 118") == (
        "Invoice 123\nVendor: Example\n\nTotal: 118"
    )


@patch("backend.llm.mistral_service._OLLAMA_SESSION.post")
@patch("backend.llm.mistral_service._OLLAMA_SESSION.get")
def test_extract_invoice_mock(mock_get, mock_post):
    mock_get.return_value.raise_for_status.return_value = None
    mock_get.return_value.json.return_value = {"models": [{"name": "qwen2.5:1.5b"}]}
    mock_post.return_value.raise_for_status.return_value = None
    mock_post.return_value.json.return_value = {
        "response": '{"invoice_number":"INV-10","invoice_date":"2026-11-22","due_date":null,"vendor_name":"Example","vendor_gstin":null,"customer_name":null,"customer_gstin":null,"items":[{"description":"Service","quantity":1,"unit_price":100,"discount":null,"taxable_value":100,"cgst":9,"sgst":9,"igst":null,"amount":118}],"subtotal":100,"cgst":9,"sgst":9,"igst":null,"total_tax":18,"grand_total":118,"currency":"INR","payment_status":"Paid"}'
    }
    result = extract_invoice("Invoice text")
    assert result.invoice_number == "INV-10"
    assert result.grand_total == 118
    request = mock_post.call_args.kwargs["json"]
    assert request["keep_alive"] in {"10m", "30m"}
    assert request["format"] == "json"
    assert request["options"]["num_ctx"] >= 512
    assert request["options"]["temperature"] == 0
    assert request["model"] == "qwen2.5:1.5b"


@patch("backend.llm.mistral_service._OLLAMA_SESSION.post")
@patch("backend.llm.mistral_service._OLLAMA_SESSION.get")
def test_missing_model_has_install_guidance(mock_get, mock_post):
    mock_get.return_value.raise_for_status.return_value = None
    mock_get.return_value.json.return_value = {"models": []}

    import pytest
    with pytest.raises(RuntimeError, match=r"ollama pull qwen2.5:1.5b"):
        extract_invoice("Invoice text")
    mock_post.assert_not_called()


@patch("backend.llm.mistral_service._OLLAMA_SESSION.post")
@patch("backend.llm.mistral_service._OLLAMA_SESSION.get")
def test_invalid_ai_response_gets_one_targeted_repair(mock_get, mock_post):
    mock_get.return_value.raise_for_status.return_value = None
    mock_get.return_value.json.return_value = {"models": [{"name": "qwen2.5:1.5b"}]}
    invalid = type("Response", (), {
        "raise_for_status": lambda self: None,
        "json": lambda self: {"response": "not json"},
    })()
    valid = type("Response", (), {
        "raise_for_status": lambda self: None,
        "json": lambda self: {"response": '{"invoice_number":"INV-10","grand_total":118}'},
    })()
    mock_post.side_effect = [invalid, valid]

    invoice = extract_invoice("Invoice text", retries=1)

    assert invoice.invoice_number == "INV-10"
    assert mock_post.call_count == 2
    prompts = [call.kwargs["json"]["prompt"] for call in mock_post.call_args_list]
    assert prompts[0] != prompts[1]
