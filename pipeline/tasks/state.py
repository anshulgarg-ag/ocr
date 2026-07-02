"""
PostgreSQL state machine for document processing.

Every document is identified by its content hash (SHA-256).
Status transitions: pending → ocr_done → chunked → embedded → graph_done → complete
Any stage can transition to failed, and after max_retries to dead_letter.
"""
from __future__ import annotations

from enum import Enum

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from config.logging import get_logger
from config.settings import settings

log = get_logger(__name__)

engine = create_async_engine(settings.postgres_url, pool_size=10, max_overflow=20)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class DocStatus(str, Enum):
    PENDING = "pending"
    OCR_DONE = "ocr_done"
    CHUNKED = "chunked"
    EMBEDDED = "embedded"
    GRAPH_DONE = "graph_done"
    COMPLETE = "complete"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"


async def register_new_documents(
    session: AsyncSession,
    files: list[dict],  # [{"file_hash": str, "s3_key_raw": str, "batch_id": str}]
) -> int:
    """Insert only truly new documents (hash not already in DB). Returns count inserted."""
    if not files:
        return 0
    result = await session.execute(
        text("""
            INSERT INTO documents (file_hash, s3_key_raw, batch_id, status)
            SELECT :file_hash, :s3_key_raw, :batch_id, 'pending'::doc_status
            FROM (VALUES (:file_hash, :s3_key_raw, :batch_id)) AS v(file_hash, s3_key_raw, batch_id)
            WHERE NOT EXISTS (
                SELECT 1 FROM documents d WHERE d.file_hash = v.file_hash
            )
        """),
        files,
    )
    await session.commit()
    inserted = result.rowcount
    log.info("documents_registered", inserted=inserted, total_provided=len(files))
    return inserted


async def get_pending(session: AsyncSession, batch_id: str) -> list[dict]:
    """Return all pending + failed (retry-eligible) docs for this batch."""
    rows = await session.execute(
        text("""
            SELECT file_hash, s3_key_raw, s3_key_md, s3_key_chunks, retry_count
            FROM documents
            WHERE batch_id = :batch_id
              AND status IN ('pending', 'failed')
              AND retry_count < :max_retries
        """),
        {"batch_id": batch_id, "max_retries": settings.max_retries},
    )
    return [dict(r._mapping) for r in rows]


async def advance(
    session: AsyncSession,
    file_hash: str,
    new_status: DocStatus,
    *,
    s3_key_md: str | None = None,
    s3_key_chunks: str | None = None,
    page_count: int | None = None,
) -> None:
    updates: dict = {"file_hash": file_hash, "status": new_status.value}
    if s3_key_md:
        updates["s3_key_md"] = s3_key_md
    if s3_key_chunks:
        updates["s3_key_chunks"] = s3_key_chunks
    if page_count is not None:
        updates["page_count"] = page_count

    set_clause = ", ".join(
        f"{k} = :{k}" for k in updates if k != "file_hash"
    )
    await session.execute(
        text(f"UPDATE documents SET {set_clause} WHERE file_hash = :file_hash"),
        updates,
    )
    await session.commit()


async def mark_failed(
    session: AsyncSession,
    file_hash: str,
    stage: str,
    error: str,
) -> bool:
    """Increment retry_count. Returns True if moved to dead_letter."""
    row = await session.execute(
        text("SELECT retry_count FROM documents WHERE file_hash = :h"),
        {"h": file_hash},
    )
    rec = row.fetchone()
    if not rec:
        return False

    retry_count = rec[0] + 1
    is_dead = retry_count >= settings.max_retries
    new_status = DocStatus.DEAD_LETTER if is_dead else DocStatus.FAILED

    await session.execute(
        text("""
            UPDATE documents
            SET status = :status, retry_count = :rc, error_msg = :err
            WHERE file_hash = :h
        """),
        {"status": new_status.value, "rc": retry_count, "err": error[:2000], "h": file_hash},
    )

    if is_dead:
        await session.execute(
            text("""
                INSERT INTO failed_documents (file_hash, failed_stage, last_error)
                VALUES (:h, :stage, :err)
            """),
            {"h": file_hash, "stage": stage, "err": error[:4000]},
        )
        log.warning("document_dead_lettered", file_hash=file_hash, stage=stage)

    await session.commit()
    return is_dead


async def count_dead_letters(session: AsyncSession, batch_id: str) -> int:
    row = await session.execute(
        text("""
            SELECT COUNT(*) FROM documents
            WHERE batch_id = :batch_id AND status = 'dead_letter'
        """),
        {"batch_id": batch_id},
    )
    return row.scalar() or 0
