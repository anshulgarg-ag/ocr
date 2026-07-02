"""
HTTP client to the BGE-M3 embedding service on JarvisLabs.
Sends text chunks, receives dense + sparse vectors, upserts to Qdrant.
"""
from __future__ import annotations

import time

import httpx
import stamina
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import PointStruct, SparseVector, VectorParams, Distance, SparseVectorParams, SparseIndexParams

from config.logging import get_logger
from config.settings import settings
from observability import metrics

log = get_logger(__name__)

DENSE_DIM = 1024  # BGE-M3 dense output dimension
COLLECTION = settings.qdrant_collection

_qdrant: AsyncQdrantClient | None = None


def get_qdrant() -> AsyncQdrantClient:
    global _qdrant
    if _qdrant is None:
        _qdrant = AsyncQdrantClient(url=settings.qdrant_url)
    return _qdrant


async def ensure_collection() -> None:
    """Create Qdrant collection if it doesn't exist. Safe to call multiple times."""
    client = get_qdrant()
    collections = await client.get_collections()
    if any(c.name == COLLECTION for c in collections.collections):
        return
    await client.create_collection(
        collection_name=COLLECTION,
        vectors_config={"dense": VectorParams(size=DENSE_DIM, distance=Distance.COSINE)},
        sparse_vectors_config={
            "sparse": SparseVectorParams(index=SparseIndexParams(on_disk=False))
        },
    )
    log.info("qdrant_collection_created", collection=COLLECTION)


@stamina.retry(on=(httpx.HTTPError, httpx.TimeoutException), attempts=3, wait_max=30.0)
async def _embed_batch(texts: list[str]) -> list[dict]:
    """Call BGE-M3 embedding service. Returns list of {"dense": [...], "sparse": {"indices": [], "values": []}}."""
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{settings.jarvis_embed_url}/embed",
            json={"texts": texts},
        )
        resp.raise_for_status()
        return resp.json()["embeddings"]


async def embed_and_upsert(chunks: list[dict]) -> int:
    """
    Embed a list of chunks and upsert to Qdrant.
    Returns number of points upserted.
    """
    client = get_qdrant()
    batch_size = settings.embed_batch_size
    total_upserted = 0

    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        texts = [c["text"] for c in batch]

        t0 = time.monotonic()
        embeddings = await _embed_batch(texts)
        elapsed_ms = (time.monotonic() - t0) * 1000
        metrics.embed_batch_duration.observe(elapsed_ms)

        points = []
        for chunk, emb in zip(batch, embeddings):
            sparse = emb.get("sparse", {})
            point = PointStruct(
                id=chunk["chunk_id"],
                vector={
                    "dense": emb["dense"],
                    "sparse": SparseVector(
                        indices=sparse.get("indices", []),
                        values=sparse.get("values", []),
                    ),
                },
                payload={
                    "doc_id": chunk["doc_id"],
                    "chunk_index": chunk["chunk_index"],
                    "heading_path": chunk.get("heading_path", ""),
                    "text": chunk["text"],
                    "token_count": chunk.get("token_count", 0),
                },
            )
            points.append(point)

        await client.upsert(collection_name=COLLECTION, points=points, wait=True)
        total_upserted += len(points)
        log.debug("qdrant_upsert", batch_i=i, count=len(points), elapsed_ms=round(elapsed_ms))

    return total_upserted
