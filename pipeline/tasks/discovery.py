"""
Discover new documents in storage that haven't been processed yet.
Uses content hash (via ETag or SHA-256) to avoid reprocessing.
"""
from __future__ import annotations

from config.logging import get_logger
from pipeline.tasks import storage_ops

log = get_logger(__name__)

SUPPORTED_EXTENSIONS = (".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp")


async def find_new_files(known_hashes: set[str]) -> list[dict]:
    """
    Scan storage raw/ prefix, compute hashes, return only files not in known_hashes.
    Returns list of {"file_hash": str, "s3_key_raw": str, "filename": str}
    """
    raw_files = storage_ops.list_files("raw", extensions=SUPPORTED_EXTENSIONS)
    log.info("discovery_scan", total_raw_files=len(raw_files))

    new_files: list[dict] = []
    for relative_path in raw_files:
        try:
            file_hash = storage_ops.etag(relative_path)
        except Exception as exc:
            log.warning("etag_failed", path=relative_path, error=str(exc))
            continue

        if file_hash not in known_hashes:
            filename = relative_path.split("/")[-1]
            new_files.append(
                {
                    "file_hash": file_hash,
                    "s3_key_raw": relative_path,
                    "filename": filename,
                }
            )

    log.info("discovery_complete", new_files=len(new_files), skipped=len(raw_files) - len(new_files))
    return new_files


async def get_known_hashes(session) -> set[str]:
    """Fetch all file hashes already in Postgres (any status)."""
    from sqlalchemy import text

    rows = await session.execute(text("SELECT file_hash FROM documents"))
    return {r[0] for r in rows}
