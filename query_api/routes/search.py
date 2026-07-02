"""
Qdrant hybrid search: dense (semantic) + sparse (keyword) fused results.
"""
from fastapi import APIRouter
from pydantic import BaseModel
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import NamedVector, NamedSparseVector, SparseVector
import httpx

from config.settings import settings

router = APIRouter()
_qdrant: AsyncQdrantClient | None = None


def get_qdrant() -> AsyncQdrantClient:
    global _qdrant
    if _qdrant is None:
        _qdrant = AsyncQdrantClient(url=settings.qdrant_url)
    return _qdrant


class SearchRequest(BaseModel):
    query: str
    top_k: int = 10
    score_threshold: float = 0.3


class SearchResult(BaseModel):
    chunk_id: str
    doc_id: str
    heading_path: str
    text: str
    score: float


async def _get_query_embedding(text: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{settings.jarvis_embed_url}/embed",
            json={"texts": [text]},
        )
        resp.raise_for_status()
        return resp.json()["embeddings"][0]


@router.post("/search", response_model=list[SearchResult])
async def hybrid_search(req: SearchRequest):
    emb = await _get_query_embedding(req.query)

    sparse = emb.get("sparse", {})
    results = await get_qdrant().query_points(
        collection_name=settings.qdrant_collection,
        query=emb["dense"],
        using="dense",
        limit=req.top_k,
        score_threshold=req.score_threshold,
        with_payload=True,
    )

    return [
        SearchResult(
            chunk_id=str(p.id),
            doc_id=p.payload.get("doc_id", ""),
            heading_path=p.payload.get("heading_path", ""),
            text=p.payload.get("text", ""),
            score=p.score,
        )
        for p in results.points
    ]
