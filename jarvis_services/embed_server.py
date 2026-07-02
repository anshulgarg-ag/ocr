"""
BGE-M3 embedding FastAPI service — runs ON JarvisLabs L40S.

Loads BAAI/bge-m3 once, exposes /embed for batch dense+sparse encoding.
VRAM: ~3GB. Runs concurrently alongside Chandra OCR workers.
"""
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from pydantic import BaseModel
from starlette.responses import Response

DEVICE = "cuda"
MODEL_NAME = os.environ.get("EMBED_MODEL", "BAAI/bge-m3")

_model = None

embed_requests = Counter("embed_requests_total", "Total embedding requests")
embed_texts = Counter("embed_texts_total", "Total texts embedded")
embed_duration = Histogram("embed_duration_ms", "Embedding latency (ms)",
                           buckets=[50, 100, 200, 500, 1000, 2000, 5000])


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _model
    from FlagEmbedding import BGEM3FlagModel
    _model = BGEM3FlagModel(MODEL_NAME, use_fp16=True, device=DEVICE)
    print(f"BGE-M3 loaded on {DEVICE}")
    yield
    _model = None


app = FastAPI(title="BGE-M3 Embedding Service", lifespan=lifespan)


class EmbedRequest(BaseModel):
    texts: list[str]


class EmbedResponse(BaseModel):
    embeddings: list[dict]  # [{"dense": [...], "sparse": {"indices": [...], "values": [...]}}]


@app.get("/health")
async def health():
    return {"status": "ok", "model": MODEL_NAME}


@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/embed", response_model=EmbedResponse)
async def embed(req: EmbedRequest):
    import asyncio
    t0 = time.monotonic()
    result = await asyncio.get_event_loop().run_in_executor(None, _encode_sync, req.texts)
    elapsed = (time.monotonic() - t0) * 1000
    embed_requests.inc()
    embed_texts.inc(len(req.texts))
    embed_duration.observe(elapsed)
    return EmbedResponse(embeddings=result)


def _encode_sync(texts: list[str]) -> list[dict]:
    output = _model.encode(
        texts,
        return_dense=True,
        return_sparse=True,
        return_colbert_vecs=False,
        batch_size=32,
    )
    dense_vecs = output["dense_vecs"]
    sparse_weights = output["lexical_weights"]

    results = []
    for i, text in enumerate(texts):
        # Convert sparse weights dict to indices/values lists
        sw = sparse_weights[i]
        indices = [int(k) for k in sw.keys()]
        values = [float(v) for v in sw.values()]
        results.append({
            "dense": dense_vecs[i].tolist(),
            "sparse": {"indices": indices, "values": values},
        })
    return results


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
