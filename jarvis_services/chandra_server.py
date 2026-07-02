"""
Chandra OCR FastAPI service — runs ON JarvisLabs.

Uses the real chandra-ocr API:
  from chandra.model import InferenceManager
  from chandra.input import load_pdf_images, load_image
  from chandra.model.schema import BatchInputItem

Reads input from MinIO (via SSH reverse tunnel at localhost:9000).
Writes Markdown output back to MinIO.
"""
import asyncio
import os
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path

import s3fs
from fastapi import FastAPI, HTTPException
from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST
from pydantic import BaseModel
from starlette.responses import Response

MINIO_ENDPOINT   = os.environ.get("MINIO_ENDPOINT", "http://localhost:9000")
MINIO_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY", "minioadmin")
STORAGE_ROOT     = os.environ.get("STORAGE_ROOT", "s3://ocr-pipeline")
MAX_WORKERS      = int(os.environ.get("OCR_WORKERS", "1"))
OCR_MODEL        = os.environ.get("OCR_MODEL", "datalab-to/chandra-ocr-2")  # local path or HF repo id

ocr_requests  = Counter("chandra_ocr_requests_total", "Total OCR requests")
ocr_errors    = Counter("chandra_ocr_errors_total",   "Total OCR errors")
ocr_pages     = Counter("chandra_ocr_pages_total",    "Total pages processed")
ocr_duration  = Histogram("chandra_ocr_duration_seconds", "OCR duration per doc",
                           buckets=[5, 10, 30, 60, 120, 300, 600])
workers_active = Gauge("chandra_workers_active", "Active OCR workers")

_semaphore: asyncio.Semaphore | None = None
_manager   = None
_fs: s3fs.S3FileSystem | None = None


def get_fs() -> s3fs.S3FileSystem:
    global _fs
    if _fs is None:
        _fs = s3fs.S3FileSystem(
            key=MINIO_ACCESS_KEY,
            secret=MINIO_SECRET_KEY,
            client_kwargs={"endpoint_url": MINIO_ENDPOINT},
        )
    return _fs


def _full_path(relative: str) -> str:
    return f"{STORAGE_ROOT.rstrip('/')}/{relative.lstrip('/')}"


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _semaphore, _manager
    _semaphore = asyncio.Semaphore(MAX_WORKERS)
    from chandra.model import InferenceManager
    _manager = InferenceManager(method="hf", model_name_or_path=OCR_MODEL)
    print(f"Chandra OCR ready. model={OCR_MODEL} workers={MAX_WORKERS}")
    yield
    _manager = None


app = FastAPI(title="Chandra OCR Service", lifespan=lifespan)


class OCRRequest(BaseModel):
    input_path: str   # relative storage path
    output_path: str  # relative storage path for output Markdown
    doc_id: str


class OCRResponse(BaseModel):
    doc_id: str
    page_count: int
    duration_ms: float
    s3_key_md: str


@app.get("/health")
async def health():
    return {"status": "ok", "workers": MAX_WORKERS}


@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/pause_worker")
async def pause_worker():
    if _semaphore:
        await _semaphore.acquire()
    return {"status": "paused"}


@app.post("/resume_worker")
async def resume_worker():
    if _semaphore:
        _semaphore.release()
    return {"status": "resumed"}


@app.post("/ocr", response_model=OCRResponse)
async def ocr_endpoint(req: OCRRequest):
    async with _semaphore:
        workers_active.inc()
        t0 = time.monotonic()
        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None, _run_ocr_sync, req.input_path, req.output_path, req.doc_id
            )
            elapsed = (time.monotonic() - t0) * 1000
            ocr_requests.inc()
            ocr_pages.inc(result["page_count"])
            ocr_duration.observe(elapsed / 1000)
            return OCRResponse(
                doc_id=req.doc_id,
                page_count=result["page_count"],
                duration_ms=round(elapsed, 1),
                s3_key_md=req.output_path,
            )
        except Exception as exc:
            ocr_errors.inc()
            raise HTTPException(status_code=500, detail=str(exc))
        finally:
            workers_active.dec()


def _run_ocr_sync(input_path: str, output_path: str, doc_id: str) -> dict:
    from chandra.input import load_pdf_images, load_image
    from chandra.model.schema import BatchInputItem

    fs = get_fs()

    with tempfile.TemporaryDirectory() as tmpdir:
        filename = Path(input_path).name
        local_input = os.path.join(tmpdir, filename)
        fs.get(_full_path(input_path), local_input)

        ext = filename.lower().rsplit(".", 1)[-1]
        if ext == "pdf":
            images = load_pdf_images(local_input, page_range=[])
        else:
            images = [load_image(local_input)]

        batch = [BatchInputItem(image=img) for img in images]
        results = _manager.generate(batch)

        # Concatenate pages into one Markdown document
        pages_md = []
        for i, r in enumerate(results):
            if not r.error:
                pages_md.append(r.markdown)

        full_md = "\n\n---\n\n".join(pages_md)

        # Upload Markdown to storage
        md_bytes = full_md.encode("utf-8")
        with fs.open(_full_path(output_path), "wb") as f:
            f.write(md_bytes)

    return {"page_count": len(images)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
