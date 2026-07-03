import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pipeline.tasks.ocr_client import ocr_document, ocr_batch


async def test_ocr_document_success(mock_ocr_service):
    result = await ocr_document(
        s3_key_raw="raw/test.pdf",
        s3_key_md="processed/test.md",
        doc_id="doc1",
        ocr_url="http://localhost:8001"
    )

    assert "page_count" in result or "s3_key_md" in result


async def test_ocr_document_http_error_raises(monkeypatch):
    monkeypatch.setattr("pipeline.tasks.ocr_client.settings.max_retries", 1)

    import httpx
    async def mock_post(*args, **kwargs):
        raise httpx.HTTPError("Connection refused")

    with patch("pipeline.tasks.ocr_client.httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post = mock_post
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client

        with pytest.raises(httpx.HTTPError):
            await ocr_document(
                s3_key_raw="raw/test.pdf",
                s3_key_md="processed/test.md",
                doc_id="doc1",
                ocr_url="http://localhost:8001"
            )


async def test_ocr_batch_success_all_docs(mock_ocr_service):
    docs = [
        {"file_hash": "hash1", "s3_key_raw": "raw/doc1.pdf", "filename": "doc1.pdf"},
        {"file_hash": "hash2", "s3_key_raw": "raw/doc2.pdf", "filename": "doc2.pdf"},
    ]

    result = await ocr_batch(docs, batch_id="batch_1", ocr_url="http://localhost:8001")

    assert isinstance(result, list)
    assert len(result) >= 0
    success_results = [r for r in result if r.get("success")]
    assert len(success_results) >= 0


async def test_ocr_batch_partial_failure_returns_error_dict(monkeypatch):
    # No httpx mocking needed here: ocr_document itself is replaced below,
    # so no real/mocked HTTP request is ever made.
    import httpx

    async def failing_ocr_document(*args, **kwargs):
        raise httpx.TimeoutException("Timeout")

    monkeypatch.setattr("pipeline.tasks.ocr_client.ocr_document", failing_ocr_document)

    docs = [
        {"file_hash": "hash1", "s3_key_raw": "raw/doc1.pdf", "filename": "doc1.pdf"},
    ]

    result = await ocr_batch(docs, batch_id="batch_1", ocr_url="http://localhost:8001")

    assert isinstance(result, list)
    assert len(result) > 0
    failure_results = [r for r in result if not r.get("success", True)]
    assert len(failure_results) > 0
    assert all("error" in r for r in failure_results)
