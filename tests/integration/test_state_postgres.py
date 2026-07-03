"""Integration tests for state.py against real PostgreSQL."""
import pytest
from sqlalchemy import text
from pipeline.tasks.state import (
    register_new_documents,
    get_pending,
    advance,
    mark_failed,
    count_dead_letters,
    DocStatus,
)


pytestmark = pytest.mark.integration


async def test_register_new_documents_inserts_and_dedupes(pg_session):
    """Verify INSERT ... WHERE NOT EXISTS prevents duplicates."""
    files = [
        {"file_hash": "hash1", "s3_key_raw": "raw/doc1.pdf", "batch_id": "batch_1"},
        {"file_hash": "hash2", "s3_key_raw": "raw/doc2.pdf", "batch_id": "batch_1"},
    ]

    count1 = await register_new_documents(pg_session, files)
    assert count1 == 2

    count2 = await register_new_documents(pg_session, files)
    assert count2 == 0

    rows = await pg_session.execute(text("SELECT COUNT(*) FROM documents"))
    assert rows.scalar() == 2


async def test_register_new_documents_empty_list_returns_zero(pg_session):
    """Verify empty file list is handled correctly."""
    count = await register_new_documents(pg_session, [])
    assert count == 0


async def test_get_pending_respects_max_retries_filter(pg_session, monkeypatch):
    """Verify get_pending filters by retry count."""
    from config.settings import settings

    monkeypatch.setattr(settings, "max_retries", 2)

    files = [
        {"file_hash": "hash1", "s3_key_raw": "raw/doc1.pdf", "batch_id": "batch_1"},
        {"file_hash": "hash2", "s3_key_raw": "raw/doc2.pdf", "batch_id": "batch_1"},
        {"file_hash": "hash3", "s3_key_raw": "raw/doc3.pdf", "batch_id": "batch_1"},
    ]

    await register_new_documents(pg_session, files)

    await pg_session.execute(
        text(
            "UPDATE documents SET retry_count = 1 WHERE file_hash = :h",
        ),
        {"h": "hash2"},
    )
    await pg_session.execute(
        text(
            "UPDATE documents SET retry_count = 2 WHERE file_hash = :h",
        ),
        {"h": "hash3"},
    )
    await pg_session.commit()

    pending = await get_pending(pg_session, "batch_1")

    hashes = {p["file_hash"] for p in pending}
    assert "hash1" in hashes
    assert "hash2" in hashes
    assert "hash3" not in hashes


async def test_advance_updates_only_provided_columns(pg_session):
    """Verify advance() only updates provided optional columns."""
    files = [{"file_hash": "hash1", "s3_key_raw": "raw/doc1.pdf", "batch_id": "batch_1"}]
    await register_new_documents(pg_session, files)

    await advance(pg_session, "hash1", DocStatus.OCR_DONE, s3_key_md="processed/doc.md")
    await pg_session.commit()

    rows = await pg_session.execute(
        text("SELECT status, s3_key_md, s3_key_chunks, page_count FROM documents WHERE file_hash = :h"),
        {"h": "hash1"},
    )
    row = rows.fetchone()
    assert row[0] == "ocr_done"
    assert row[1] == "processed/doc.md"
    assert row[2] is None
    assert row[3] is None


async def test_advance_with_all_kwargs(pg_session):
    """Verify advance() with all optional parameters."""
    files = [{"file_hash": "hash1", "s3_key_raw": "raw/doc1.pdf", "batch_id": "batch_1"}]
    await register_new_documents(pg_session, files)

    await advance(
        pg_session,
        "hash1",
        DocStatus.CHUNKED,
        s3_key_md="processed/doc.md",
        s3_key_chunks="chunks/doc.jsonl",
        page_count=5,
    )
    await pg_session.commit()

    rows = await pg_session.execute(
        text(
            "SELECT status, s3_key_md, s3_key_chunks, page_count FROM documents WHERE file_hash = :h"
        ),
        {"h": "hash1"},
    )
    row = rows.fetchone()
    assert row[0] == "chunked"
    assert row[1] == "processed/doc.md"
    assert row[2] == "chunks/doc.jsonl"
    assert row[3] == 5


async def test_mark_failed_below_max_retries(pg_session, monkeypatch):
    """Verify mark_failed sets status to FAILED when below max retries."""
    from config.settings import settings

    monkeypatch.setattr(settings, "max_retries", 3)

    files = [{"file_hash": "hash1", "s3_key_raw": "raw/doc1.pdf", "batch_id": "batch_1"}]
    await register_new_documents(pg_session, files)

    is_dead = await mark_failed(pg_session, "hash1", "ocr", "OCR timeout")
    await pg_session.commit()

    assert is_dead is False

    rows = await pg_session.execute(
        text("SELECT status, retry_count FROM documents WHERE file_hash = :h"),
        {"h": "hash1"},
    )
    row = rows.fetchone()
    assert row[0] == "failed"
    assert row[1] == 1


async def test_mark_failed_at_max_retries_creates_dead_letter(pg_session, monkeypatch):
    """Verify mark_failed creates a dead_letter record at max retries."""
    from config.settings import settings

    monkeypatch.setattr(settings, "max_retries", 2)

    files = [{"file_hash": "hash1", "s3_key_raw": "raw/doc1.pdf", "batch_id": "batch_1"}]
    await register_new_documents(pg_session, files)

    await pg_session.execute(
        text("UPDATE documents SET retry_count = :rc WHERE file_hash = :h"),
        {"rc": 1, "h": "hash1"},
    )
    await pg_session.commit()

    is_dead = await mark_failed(pg_session, "hash1", "ocr", "OCR timeout")
    await pg_session.commit()

    assert is_dead is True

    rows = await pg_session.execute(
        text("SELECT status, retry_count FROM documents WHERE file_hash = :h"),
        {"h": "hash1"},
    )
    row = rows.fetchone()
    assert row[0] == "dead_letter"
    assert row[1] == 2

    dl_rows = await pg_session.execute(
        text("SELECT failed_stage FROM failed_documents WHERE file_hash = :h"),
        {"h": "hash1"},
    )
    assert dl_rows.scalar() == "ocr"


async def test_mark_failed_row_not_found_returns_false(pg_session):
    """Verify mark_failed returns False for nonexistent file."""
    is_dead = await mark_failed(pg_session, "nonexistent", "ocr", "Error")
    assert is_dead is False


async def test_count_dead_letters_counts_real_rows(pg_session, monkeypatch):
    """Verify count_dead_letters returns actual dead letter count."""
    from config.settings import settings

    monkeypatch.setattr(settings, "max_retries", 1)

    files = [
        {"file_hash": "hash1", "s3_key_raw": "raw/doc1.pdf", "batch_id": "batch_1"},
        {"file_hash": "hash2", "s3_key_raw": "raw/doc2.pdf", "batch_id": "batch_1"},
    ]
    await register_new_documents(pg_session, files)

    await mark_failed(pg_session, "hash1", "ocr", "Error 1")
    await pg_session.commit()

    await mark_failed(pg_session, "hash2", "ocr", "Error 2")
    await pg_session.commit()

    count = await count_dead_letters(pg_session, "batch_1")
    assert count == 2


async def test_count_dead_letters_empty_batch(pg_session):
    """Verify count_dead_letters returns 0 for batch with no dead letters."""
    count = await count_dead_letters(pg_session, "nonexistent_batch")
    assert count == 0
