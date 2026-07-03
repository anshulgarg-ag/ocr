"""
Main Prefect batch ingestion flow.

Stages:
  1. Discover new files in storage
  2. Start JarvisLabs GPU instance
  3. OCR all new documents (Chandra, 3 workers)
  4. Chunk all OCR'd Markdown
  5. Embed chunks → Qdrant
  6. Extract entities → Neo4j (full knowledge graph)
  7. Stop JarvisLabs instance (always)

Run manually:  python -m pipeline.flows.batch_ingest
Schedule:      prefect deploy --cron "0 2 * * *"
"""
from __future__ import annotations

import asyncio
import time
import uuid

from prefect import flow, task, get_run_logger
from prefect.tasks import task_input_hash

from config.logging import configure_logging, get_logger
from config.settings import settings
from observability.alerts import alert_flow_failed, alert_dead_letter_spike
from observability.metrics import docs_processed, start_metrics_server
from observability.tracing import init_tracing, get_tracer
from pipeline.tasks import storage_ops, discovery, state, ocr_client, chunker, embed_client, neo4j_writer
from pipeline.providers.factory import create_gpu_provider

configure_logging()
log = get_logger(__name__)

_provider = None


@task(retries=2, retry_delay_seconds=30)
async def task_discover(batch_id: str) -> list[dict]:
    async with state.AsyncSessionLocal() as session:
        known = await discovery.get_known_hashes(session)
        new_files = await discovery.find_new_files(known)
        await state.register_new_documents(
            session,
            [{"file_hash": f["file_hash"], "s3_key_raw": f["s3_key_raw"], "batch_id": batch_id}
             for f in new_files],
        )
    return new_files


@task(retries=1, retry_delay_seconds=60)
async def task_start_gpu() -> dict:
    global _provider
    _provider = create_gpu_provider()
    endpoints = await _provider.start()
    await _provider.wait_for_services(timeout=300)
    return {
        "ocr_url": endpoints.ocr_url,
        "embed_url": endpoints.embed_url,
        "graph_url": endpoints.graph_url,
        "storage_url": endpoints.storage_url,
    }


@task
async def task_ocr(docs: list[dict], batch_id: str, endpoints: dict) -> list[dict]:
    results = await ocr_client.ocr_batch(docs, batch_id, endpoints["ocr_url"])
    async with state.AsyncSessionLocal() as session:
        for r in results:
            if r["success"]:
                await state.advance(
                    session,
                    r["file_hash"],
                    state.DocStatus.OCR_DONE,
                    s3_key_md=r.get("s3_key_md"),
                    page_count=r.get("page_count"),
                )
            else:
                await state.mark_failed(session, r["file_hash"], "ocr", r["error"])
    return [r for r in results if r["success"]]


@task
async def task_chunk(ocr_results: list[dict]) -> list[dict]:
    """Chunk all OCR'd Markdown documents. Returns list of {file_hash, s3_key_chunks, chunks}."""
    all_results = []
    async with state.AsyncSessionLocal() as session:
        for r in ocr_results:
            try:
                md_text = storage_ops.read_text(r["s3_key_md"])
                chunks = chunker.chunk_markdown(md_text, r["file_hash"])
                jsonl = chunker.chunks_to_jsonl(chunks)
                s3_key_chunks = r["s3_key_md"].replace("processed/", "chunks/").replace(".md", ".jsonl")
                storage_ops.write_text(jsonl, s3_key_chunks)
                await state.advance(
                    session, r["file_hash"], state.DocStatus.CHUNKED, s3_key_chunks=s3_key_chunks
                )
                all_results.append({**r, "s3_key_chunks": s3_key_chunks, "chunks": chunks})
            except Exception as exc:
                log.error("chunking_failed", doc_id=r["file_hash"], error=str(exc))
                await state.mark_failed(session, r["file_hash"], "chunking", str(exc))
    return all_results


@task(retries=2, retry_delay_seconds=15)
async def task_embed(chunked_results: list[dict], endpoints: dict) -> None:
    await embed_client.ensure_collection()
    async with state.AsyncSessionLocal() as session:
        for r in chunked_results:
            try:
                count = await embed_client.embed_and_upsert(r["chunks"], endpoints["embed_url"])
                log.info("embedded", doc_id=r["file_hash"], vectors=count)
                await state.advance(session, r["file_hash"], state.DocStatus.EMBEDDED)
            except Exception as exc:
                log.error("embedding_failed", doc_id=r["file_hash"], error=str(exc))
                await state.mark_failed(session, r["file_hash"], "embedding", str(exc))


@task(retries=1, retry_delay_seconds=30)
async def task_graph(chunked_results: list[dict], original_docs: list[dict], endpoints: dict) -> None:
    """Pause 1 OCR worker, run entity extraction, write full KG to Neo4j."""
    await neo4j_writer.setup_constraints()

    # Signal OCR service to release 1 worker slot for VRAM headroom
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(f"{endpoints['ocr_url']}/pause_worker")
    except Exception:
        pass  # Not fatal if OCR is already idle

    doc_map = {d["file_hash"]: d for d in original_docs}

    async with state.AsyncSessionLocal() as session:
        for r in chunked_results:
            try:
                doc_meta = doc_map.get(r["file_hash"], {})
                # Write structural KG (Document → Section → Chunk)
                await neo4j_writer.upsert_document({
                    **doc_meta,
                    "file_hash": r["file_hash"],
                    "s3_key_md": r.get("s3_key_md", ""),
                    "chunks": r["chunks"],
                })

                # Entity extraction via LightRAG + Qwen2.5-7B on JarvisLabs
                md_text = storage_ops.read_text(r["s3_key_md"])
                import httpx as _httpx
                async with _httpx.AsyncClient(timeout=300) as client:
                    resp = await client.post(
                        f"{endpoints['graph_url']}/extract",
                        json={"text": md_text, "doc_id": r["file_hash"]},
                    )
                    resp.raise_for_status()
                    graph_data = resp.json()

                await neo4j_writer.upsert_entities(
                    r["file_hash"],
                    graph_data.get("entities", []),
                    graph_data.get("relations", []),
                )
                await state.advance(session, r["file_hash"], state.DocStatus.GRAPH_DONE)
            except Exception as exc:
                log.error("graph_failed", doc_id=r["file_hash"], error=str(exc))
                await state.mark_failed(session, r["file_hash"], "graph", str(exc))


@flow(name="batch-ingest", log_prints=True)
async def batch_ingest_flow() -> dict:
    batch_id = str(uuid.uuid4())[:8]
    start_time = time.monotonic()

    # Everything below is wrapped in try/finally so GPU provider cleanup runs
    # even if logger setup, discovery, or any later stage fails.
    try:
        logger = get_run_logger()
        logger.info(f"Batch {batch_id} starting")

        # Ensure storage bucket exists
        storage_ops.ensure_bucket()

        # Stage 1: Discover
        new_files = await task_discover(batch_id)
        if not new_files:
            logger.info("No new files found. Batch done.")
            return {"batch_id": batch_id, "new_files": 0}

        logger.info(f"Found {len(new_files)} new documents")

        # Stage 2: Start GPU provider (always stopped in finally)
        endpoints = await task_start_gpu()

        # Stage 3: OCR
        ocr_results = await task_ocr(new_files, batch_id, endpoints)
        logger.info(f"OCR complete: {len(ocr_results)}/{len(new_files)} succeeded")

        if not ocr_results:
            return {"batch_id": batch_id, "ocr_succeeded": 0}

        # Stage 4: Chunk
        chunked = await task_chunk(ocr_results)

        # Stage 5: Embed → Qdrant
        await task_embed(chunked, endpoints)

        # Stage 6: Graph → Neo4j (full knowledge graph)
        await task_graph(chunked, new_files, endpoints)

        # Finalize
        async with state.AsyncSessionLocal() as session:
            for r in [c for c in chunked if c]:
                await state.advance(session, r["file_hash"], state.DocStatus.COMPLETE)
            dl_count = await state.count_dead_letters(session, batch_id)

        docs_processed.labels(batch_id=batch_id).inc(len(chunked))
        await alert_dead_letter_spike(dl_count)

        elapsed = round(time.monotonic() - start_time, 1)
        logger.info(f"Batch {batch_id} complete: {len(chunked)} docs in {elapsed}s, {dl_count} dead-lettered")
        return {
            "batch_id": batch_id,
            "new_files": len(new_files),
            "ocr_succeeded": len(ocr_results),
            "embedded": len(chunked),
            "dead_lettered": dl_count,
            "elapsed_s": elapsed,
        }

    except Exception as exc:
        log.error("batch_flow_failed", batch_id=batch_id, error=str(exc))
        await alert_flow_failed(batch_id, str(exc))
        raise
    finally:
        global _provider
        if _provider:
            try:
                await _provider.stop()
            except Exception as stop_exc:
                log.error("gpu_provider_stop_failed_in_finally", error=str(stop_exc))
                _provider = None


if __name__ == "__main__":
    asyncio.run(batch_ingest_flow())
