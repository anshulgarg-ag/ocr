"""
Neo4j knowledge graph queries: entity lookup, subgraph exploration, path finding.
"""
from fastapi import APIRouter
from pydantic import BaseModel
from neo4j import AsyncGraphDatabase, AsyncDriver

from config.settings import settings

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


class EntitySearchRequest(BaseModel):
    entity_name: str
    entity_type: str | None = None
    depth: int = 2


class DocumentsByEntityRequest(BaseModel):
    entity_name: str
    limit: int = 20


@router.get("/entities/{name}")
async def get_entity_subgraph(name: str, depth: int = 2):
    """Return an entity and its neighborhood in the knowledge graph."""
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (e:Entity {name: $name})
            CALL apoc.path.subgraphNodes(e, {maxLevel: $depth, relationshipFilter: 'MENTIONS>'})
            YIELD node
            WITH collect(node) AS nodes
            UNWIND nodes AS n
            OPTIONAL MATCH (n)-[r]->(m) WHERE m IN nodes
            RETURN n, r, m LIMIT 200
            """,
            {"name": name, "depth": depth},
        )
        records = await result.data()
    return {"entity": name, "subgraph": records}


@router.post("/documents-by-entity")
async def documents_mentioning_entity(req: DocumentsByEntityRequest):
    """Find all documents that mention an entity, sorted by frequency."""
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (e:Entity {name: $name})-[r:APPEARS_IN]->(d:Document)
            RETURN d.id AS doc_id, d.filename AS filename, r.confidence AS confidence
            ORDER BY r.confidence DESC
            LIMIT $limit
            """,
            {"name": req.entity_name, "limit": req.limit},
        )
        rows = await result.data()
    return {"entity": req.entity_name, "documents": rows}


@router.get("/document/{doc_id}/graph")
async def document_knowledge_graph(doc_id: str):
    """Return the full knowledge graph for a single document."""
    driver = get_driver()
    async with driver.session() as session:
        # Document structure
        structure = await (await session.run(
            """
            MATCH (d:Document {id: $doc_id})-[:HAS_SECTION]->(s:Section)-[:HAS_CHUNK]->(c:Chunk)
            RETURN d.filename AS filename, s.heading AS section, s.heading_path AS heading_path,
                   c.chunk_id AS chunk_id, c.token_count AS tokens
            ORDER BY s.level, c.chunk_index
            """,
            {"doc_id": doc_id},
        )).data()

        # Entities in this document
        entities = await (await session.run(
            """
            MATCH (e:Entity)-[r:APPEARS_IN]->(d:Document {id: $doc_id})
            RETURN e.name AS name, e.type AS type, r.confidence AS confidence
            ORDER BY r.confidence DESC
            """,
            {"doc_id": doc_id},
        )).data()

    return {"doc_id": doc_id, "structure": structure, "entities": entities}


@router.get("/cooccurring-entities")
async def cooccurring_entities(entity_a: str, entity_b: str):
    """Find documents where both entities appear and their relationship path."""
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (a:Entity {name: $a})-[:APPEARS_IN]->(d:Document)<-[:APPEARS_IN]-(b:Entity {name: $b})
            RETURN d.id AS doc_id, d.filename AS filename
            ORDER BY d.filename
            """,
            {"a": entity_a, "b": entity_b},
        )
        rows = await result.data()
    return {"entity_a": entity_a, "entity_b": entity_b, "shared_documents": rows}
