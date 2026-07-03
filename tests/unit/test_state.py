import pytest
from unittest.mock import AsyncMock, MagicMock
from pipeline.tasks.state import (
    register_new_documents,
    get_pending,
    advance,
    mark_failed,
    count_dead_letters,
    DocStatus,
)


async def test_register_new_documents_empty_returns_zero(fake_session):
    result = await register_new_documents(fake_session, [])
    assert result == 0
    fake_session.execute.assert_not_called()


async def test_register_new_documents_inserts_and_commits(fake_session):
    files = [
        {"file_hash": "hash1", "s3_key_raw": "raw/doc1.pdf", "batch_id": "batch_1"},
        {"file_hash": "hash2", "s3_key_raw": "raw/doc2.pdf", "batch_id": "batch_1"},
    ]
    mock_result = MagicMock()
    mock_result.rowcount = 2
    fake_session.execute.return_value = mock_result

    result = await register_new_documents(fake_session, files)

    assert result == 2
    fake_session.execute.assert_called_once()
    fake_session.commit.assert_called_once()


async def test_get_pending_converts_rows_to_dicts(fake_session):
    mock_row = MagicMock()
    mock_row._mapping = {
        "file_hash": "hash1",
        "s3_key_raw": "raw/doc1.pdf",
        "s3_key_md": None,
        "s3_key_chunks": None,
        "retry_count": 0,
    }
    mock_result = MagicMock()
    mock_result.__iter__.return_value = iter([mock_row])
    fake_session.execute.return_value = mock_result

    result = await get_pending(fake_session, "batch_1")

    assert len(result) == 1
    assert result[0]["file_hash"] == "hash1"
    assert result[0]["retry_count"] == 0


async def test_advance_no_optional_kwargs(fake_session):
    await advance(fake_session, "hash1", DocStatus.OCR_DONE)

    fake_session.execute.assert_called_once()
    fake_session.commit.assert_called_once()
    call_args = fake_session.execute.call_args[0][0]
    assert "status" in str(call_args)
    assert "s3_key_md" not in str(call_args)


async def test_advance_with_s3_key_md(fake_session):
    await advance(fake_session, "hash1", DocStatus.OCR_DONE, s3_key_md="processed/doc.md")

    call_args = fake_session.execute.call_args[0][0]
    assert "s3_key_md" in str(call_args)


async def test_advance_with_all_kwargs(fake_session):
    await advance(
        fake_session,
        "hash1",
        DocStatus.CHUNKED,
        s3_key_md="processed/doc.md",
        s3_key_chunks="chunks/doc.jsonl",
        page_count=5,
    )

    call_args = fake_session.execute.call_args[0][0]
    assert "s3_key_md" in str(call_args)
    assert "s3_key_chunks" in str(call_args)
    assert "page_count" in str(call_args)


async def test_mark_failed_row_not_found_returns_false_no_commit(fake_session):
    mock_result = MagicMock()
    mock_result.fetchone = MagicMock(return_value=None)
    fake_session.execute.return_value = mock_result

    result = await mark_failed(fake_session, "nonexistent", "ocr", "File not found")

    assert result is False
    fake_session.commit.assert_not_called()


async def test_mark_failed_below_max_retries_sets_failed_single_update(fake_session, monkeypatch):
    monkeypatch.setattr("pipeline.tasks.state.settings.max_retries", 3)
    mock_result = MagicMock()
    mock_result.fetchone = MagicMock(return_value=(0,))

    async def execute_side_effect(query, *args, **kwargs):
        if "retry_count" in str(query):
            return mock_result
        return AsyncMock()

    fake_session.execute.side_effect = execute_side_effect

    result = await mark_failed(fake_session, "hash1", "ocr", "OCR service timeout")

    assert result is False
    assert fake_session.execute.call_count == 2
    fake_session.commit.assert_called_once()


async def test_mark_failed_at_max_retries_sets_dead_letter_and_inserts(fake_session, monkeypatch):
    monkeypatch.setattr("pipeline.tasks.state.settings.max_retries", 3)
    mock_result = MagicMock()
    mock_result.fetchone = MagicMock(return_value=(2,))

    fake_session.execute.return_value = mock_result

    result = await mark_failed(fake_session, "hash1", "ocr", "OCR service timeout")

    assert result is True
    assert fake_session.execute.call_count >= 2
    fake_session.commit.assert_called_once()


async def test_count_dead_letters_returns_zero_when_scalar_none(fake_session):
    mock_result = MagicMock()
    mock_result.scalar.return_value = None
    fake_session.execute.return_value = mock_result

    result = await count_dead_letters(fake_session, "batch_1")

    assert result == 0


async def test_count_dead_letters_returns_count(fake_session):
    mock_result = MagicMock()
    mock_result.scalar.return_value = 5
    fake_session.execute.return_value = mock_result

    result = await count_dead_letters(fake_session, "batch_1")

    assert result == 5
