"""
HTTP client to the Chandra OCR FastAPI service on JarvisLabs.
Submits documents by storage path (JarvisLabs reads/writes directly from storage).
"""
from __future__ import annotations

import asyncio

import httpx
import stamina

from config.logging import get_logger
from config.settings import settings
from observability import metrics

log = get_logger(__name__)


@stamina.retry(on=(httpx.HTTPError, httpx.TimeoutException), attempts=settings.max_retries, wait_max=30.0)
async def ocr_document(s3_key_raw: str, s3_key_md: str, doc_id: str) -> dict:
    """
    Ask the Chandra OCR service to process one document.
    JarvisLabs reads from storage directly, writes Markdown back, returns metadata.
    Returns: {"page_count": int, "duration_ms": float, "s3_key_md": str}
    """
    url = f"{settings.jarvis_ocr_url}/ocr"
    payload = {
        "input_path": s3_key_raw,
        "output_path": s3_key_md,
        "doc_id": doc_id,
    }
    async with httpx.AsyncClient(timeout=600) as client:  # 10 min timeout per doc
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        result = resp.json()

    log.info(
        "ocr_complete",
        doc_id=doc_id,
        page_count=result.get("page_count"),
        duration_ms=result.get("duration_ms"),
    )
    return result


async def ocr_batch(docs: list[dict], batch_id: str) -> list[dict]:
    """
    Process multiple documents concurrently, bounded by OCR_WORKERS semaphore.
    Each doc: {"file_hash": str, "s3_key_raw": str, "filename": str}
    Returns: list of result dicts (with "file_hash", "success", "error", "page_count")
    """
    sem = asyncio.Semaphore(settings.ocr_workers)
    results = []

    async def _process(doc: dict) -> dict:
        async with sem:
            file_hash = doc["file_hash"]
            filename_stem = doc["filename"].rsplit(".", 1)[0]
            s3_key_md = f"processed/{filename_stem}.md"
            start = asyncio.get_event_loop().time()
            metrics.docs_in_flight.inc()
            try:
                result = await ocr_document(doc["s3_key_raw"], s3_key_md, file_hash)
                duration = (asyncio.get_event_loop().time() - start) * 1000
                metrics.ocr_duration.observe(duration / 1000)
                return {
                    "file_hash": file_hash,
                    "s3_key_md": s3_key_md,
                    "page_count": result.get("page_count", 0),
                    "success": True,
                    "error": None,
                }
            except Exception as exc:
                log.error("ocr_failed", doc_id=file_hash, error=str(exc))
                metrics.docs_failed.labels(stage="ocr").inc()
                return {"file_hash": file_hash, "success": False, "error": str(exc)}
            finally:
                metrics.docs_in_flight.dec()

    tasks = [asyncio.create_task(_process(doc)) for doc in docs]
    for coro in asyncio.as_completed(tasks):
        results.append(await coro)

    return results
