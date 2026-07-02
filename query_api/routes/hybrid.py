"""
Hybrid query: Qdrant semantic search + Neo4j graph context, fused into a single response.

Workflow:
  1. Qdrant hybrid search → top-K chunk IDs + doc IDs
  2. Neo4j: for each doc, fetch entity context and related documents
  3. Fuse: return chunks with their graph context attached
"""
from fastapi import APIRouter
from pydantic import BaseModel
from neo4j import AsyncGraphDatabase, AsyncDriver

from config.settings import settings
from query_api.routes.search import hybrid_search, SearchRequest

router = APIRouter()
_driver: AsyncDriver | None = None


def get_driver() -> AsyncDriver:
    global _driver
    if _driver is None:
        _driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
    return _driver


class HybridRequest(BaseModel):
    query: str
    top_k: int = 10
    include_graph_context: bool = True


class ChunkWithContext(BaseModel):
    chunk_id: str
    doc_id: str
    heading_path: str
    text: str
    vector_score: float
    entities: list[dict] = []
    related_docs: list[str] = []


@router.post("/hybrid", response_model=list[ChunkWithContext])
async def hybrid_query(req: HybridRequest):
    # Step 1: Vector search
    chunks = await hybrid_search(SearchRequest(query=req.query, top_k=req.top_k))

    if not req.include_graph_context or not chunks:
        return [ChunkWithContext(**c.model_dump(), vector_score=c.score) for c in chunks]

    # Step 2: Graph context per unique doc
    doc_ids = list({c.doc_id for c in chunks})
    driver = get_driver()

    doc_context: dict[str, dict] = {}
    async with driver.session() as session:
        for doc_id in doc_ids:
            entities_result = await session.run(
                """
                MATCH (e:Entity)-[:APPEARS_IN]->(d:Document {id: $doc_id})
                RETURN e.name AS name, e.type AS type
                ORDER BY e.type LIMIT 20
                """,
                {"doc_id": doc_id},
            )
            entities = await entities_result.data()

            related_result = await session.run(
                """
                MATCH (d:Document {id: $doc_id})-[:REFERENCES]->(r:Document)
                RETURN r.filename AS filename LIMIT 5
                """,
                {"doc_id": doc_id},
            )
            related = [row["filename"] for row in await related_result.data()]
            doc_context[doc_id] = {"entities": entities, "related_docs": related}

    # Step 3: Fuse
    return [
        ChunkWithContext(
            chunk_id=c.chunk_id,
            doc_id=c.doc_id,
            heading_path=c.heading_path,
            text=c.text,
            vector_score=c.score,
            entities=doc_context.get(c.doc_id, {}).get("entities", []),
            related_docs=doc_context.get(c.doc_id, {}).get("related_docs", []),
        )
        for c in chunks
    ]
