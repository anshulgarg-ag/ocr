"""
Neo4j knowledge graph writer.

Graph schema:
  (:Document {id, filename, batch_id, page_count, s3_key_raw, s3_key_md})
    -[:HAS_SECTION]→ (:Section {heading, level, doc_id, heading_path})
      -[:HAS_CHUNK]→ (:Chunk {chunk_id, doc_id, chunk_index, token_count, text_preview})

  (:Entity {name, type})
    -[:APPEARS_IN {confidence, doc_id}]→ (:Document)
    -[:MENTIONS {confidence, doc_id}]→ (:Entity)

  (:Document)-[:REFERENCES {doc_id}]→ (:Document)

All writes use MERGE (idempotent). Uniqueness constraints must be created before first run.
"""
from __future__ import annotations

import time

import stamina
from neo4j import AsyncGraphDatabase, AsyncDriver

from config.logging import get_logger
from config.settings import settings
from observability import metrics

log = get_logger(__name__)

_driver: AsyncDriver | None = None


def get_driver() -> AsyncDriver:
    global _driver
    if _driver is None:
        _driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
    return _driver


async def setup_constraints() -> None:
    """Create uniqueness constraints and indexes. Safe to call multiple times."""
    driver = get_driver()
    async with driver.session() as session:
        statements = [
            "CREATE CONSTRAINT doc_id IF NOT EXISTS FOR (d:Document) REQUIRE d.id IS UNIQUE",
            "CREATE CONSTRAINT entity_name_type IF NOT EXISTS FOR (e:Entity) REQUIRE (e.name, e.type) IS UNIQUE",
            "CREATE CONSTRAINT chunk_id IF NOT EXISTS FOR (c:Chunk) REQUIRE c.chunk_id IS UNIQUE",
            "CREATE INDEX doc_batch_id IF NOT EXISTS FOR (d:Document) ON (d.batch_id)",
            "CREATE INDEX entity_type IF NOT EXISTS FOR (e:Entity) ON (e.type)",
        ]
        for stmt in statements:
            await session.run(stmt)
    log.info("neo4j_constraints_ready")


async def upsert_document(doc: dict) -> None:
    """
    Merge the Document node and its Section + Chunk subgraph.

    doc = {
      "file_hash": str,        → Document.id
      "filename": str,
      "batch_id": str,
      "page_count": int,
      "s3_key_raw": str,
      "s3_key_md": str,
      "chunks": [{"chunk_id", "chunk_index", "heading_path", "text", "token_count"}]
    }
    """
    driver = get_driver()
    t0 = time.monotonic()

    async with driver.session() as session:
        # Merge document node
        await session.run(
            """
            MERGE (d:Document {id: $id})
            SET d.filename = $filename,
                d.batch_id = $batch_id,
                d.page_count = $page_count,
                d.s3_key_raw = $s3_key_raw,
                d.s3_key_md  = $s3_key_md
            """,
            {
                "id": doc["file_hash"],
                "filename": doc.get("filename", ""),
                "batch_id": doc.get("batch_id", ""),
                "page_count": doc.get("page_count", 0),
                "s3_key_raw": doc.get("s3_key_raw", ""),
                "s3_key_md": doc.get("s3_key_md", ""),
            },
        )

        # Merge sections and chunks
        seen_sections: dict[str, bool] = {}
        for chunk in doc.get("chunks", []):
            heading_path = chunk.get("heading_path", "")
            section_key = f"{doc['file_hash']}:{heading_path}"

            if section_key not in seen_sections:
                parts = heading_path.split(" > ")
                heading = parts[-1] if parts else heading_path
                level = len(parts)
                await session.run(
                    """
                    MATCH (d:Document {id: $doc_id})
                    MERGE (s:Section {heading_path: $heading_path, doc_id: $doc_id})
                    SET s.heading = $heading, s.level = $level
                    MERGE (d)-[:HAS_SECTION]->(s)
                    """,
                    {
                        "doc_id": doc["file_hash"],
                        "heading_path": heading_path,
                        "heading": heading,
                        "level": level,
                    },
                )
                seen_sections[section_key] = True

            # Merge chunk node (text_preview only — full text is in Qdrant)
            await session.run(
                """
                MATCH (s:Section {heading_path: $heading_path, doc_id: $doc_id})
                MERGE (c:Chunk {chunk_id: $chunk_id})
                SET c.doc_id = $doc_id,
                    c.chunk_index = $chunk_index,
                    c.token_count = $token_count,
                    c.text_preview = $text_preview
                MERGE (s)-[:HAS_CHUNK]->(c)
                """,
                {
                    "heading_path": heading_path,
                    "doc_id": doc["file_hash"],
                    "chunk_id": chunk["chunk_id"],
                    "chunk_index": chunk["chunk_index"],
                    "token_count": chunk.get("token_count", 0),
                    "text_preview": chunk.get("text", "")[:200],
                },
            )

    elapsed_ms = (time.monotonic() - t0) * 1000
    metrics.neo4j_write_latency.observe(elapsed_ms)
    log.debug("neo4j_doc_upserted", doc_id=doc["file_hash"], chunks=len(doc.get("chunks", [])))


async def upsert_entities(doc_id: str, entities: list[dict], relations: list[dict]) -> None:
    """
    Merge entities and relationships extracted by LightRAG.

    entities: [{"name": str, "type": str, "confidence": float, "source_text": str}]
    relations: [{"source": str, "source_type": str, "target": str, "target_type": str,
                 "relation_type": str, "confidence": float}]
    """
    driver = get_driver()
    confidence_min = settings.entity_confidence_min

    async with driver.session() as session:
        for ent in entities:
            if ent.get("confidence", 1.0) < confidence_min:
                continue
            await session.run(
                """
                MERGE (e:Entity {name: $name, type: $type})
                WITH e
                MATCH (d:Document {id: $doc_id})
                MERGE (e)-[r:APPEARS_IN]->(d)
                SET r.confidence = $confidence
                """,
                {
                    "name": ent["name"],
                    "type": ent.get("type", "UNKNOWN"),
                    "doc_id": doc_id,
                    "confidence": ent.get("confidence", 1.0),
                },
            )

        for rel in relations:
            if rel.get("confidence", 1.0) < confidence_min:
                continue
            await session.run(
                """
                MERGE (a:Entity {name: $src_name, type: $src_type})
                MERGE (b:Entity {name: $tgt_name, type: $tgt_type})
                MERGE (a)-[r:MENTIONS {doc_id: $doc_id}]->(b)
                SET r.relation_type = $rel_type, r.confidence = $confidence
                """,
                {
                    "src_name": rel["source"],
                    "src_type": rel.get("source_type", "UNKNOWN"),
                    "tgt_name": rel["target"],
                    "tgt_type": rel.get("target_type", "UNKNOWN"),
                    "doc_id": doc_id,
                    "rel_type": rel.get("relation_type", "RELATED_TO"),
                    "confidence": rel.get("confidence", 1.0),
                },
            )

    log.debug(
        "neo4j_entities_upserted",
        doc_id=doc_id,
        entities=len(entities),
        relations=len(relations),
    )
