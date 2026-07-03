"""Integration tests for neo4j_writer.py against real Neo4j."""
import pytest
from pipeline.tasks import neo4j_writer


pytestmark = pytest.mark.integration


async def test_setup_constraints_idempotent(neo4j_session):
    """Verify setup_constraints() can be called multiple times without error."""
    monkeypatch_obj = pytest.MonkeyPatch()

    def mock_get_driver():
        return neo4j_session._driver

    monkeypatch_obj.setattr(neo4j_writer, "get_driver", mock_get_driver)

    await neo4j_writer.setup_constraints()
    await neo4j_writer.setup_constraints()


async def test_upsert_document_creates_nodes_and_relationships(neo4j_session):
    """Verify upsert_document creates Document, Section, and Chunk nodes."""
    from unittest.mock import patch

    with patch("pipeline.tasks.neo4j_writer.get_driver") as mock_get_driver:
        mock_get_driver.return_value._driver

        test_doc = {
            "file_hash": "test-hash-001",
            "filename": "test.pdf",
            "batch_id": "batch_test",
            "page_count": 3,
            "s3_key_raw": "raw/test.pdf",
            "s3_key_md": "processed/test.md",
            "chunks": [
                {
                    "chunk_id": "chunk-1",
                    "chunk_index": 0,
                    "heading_path": "Introduction",
                    "text": "This is the introduction section with enough content.",
                    "token_count": 10,
                },
                {
                    "chunk_id": "chunk-2",
                    "chunk_index": 1,
                    "heading_path": "Introduction > Subsection",
                    "text": "This is a subsection with more details.",
                    "token_count": 8,
                },
            ],
        }

        await neo4j_writer.upsert_document(test_doc)

        session = neo4j_session
        result = session.run(
            "MATCH (d:Document {id: $doc_id}) RETURN d",
            {"doc_id": "test-hash-001"},
        )
        assert result.single() is not None

        result = session.run(
            "MATCH (s:Section {doc_id: $doc_id}) RETURN count(s) as cnt",
            {"doc_id": "test-hash-001"},
        )
        assert result.single()["cnt"] >= 1

        result = session.run(
            "MATCH (c:Chunk {doc_id: $doc_id}) RETURN count(c) as cnt",
            {"doc_id": "test-hash-001"},
        )
        assert result.single()["cnt"] == 2


async def test_upsert_document_dedupes_sections(neo4j_session):
    """Verify repeated upserts don't create duplicate Section nodes."""
    from unittest.mock import patch

    with patch("pipeline.tasks.neo4j_writer.get_driver") as mock_get_driver:
        mock_get_driver.return_value._driver

        test_doc_1 = {
            "file_hash": "test-dedup-001",
            "filename": "test.pdf",
            "batch_id": "batch_test",
            "page_count": 1,
            "s3_key_raw": "raw/test.pdf",
            "s3_key_md": "processed/test.md",
            "chunks": [
                {
                    "chunk_id": "chunk-1",
                    "chunk_index": 0,
                    "heading_path": "Main Section",
                    "text": "Content",
                    "token_count": 5,
                }
            ],
        }

        await neo4j_writer.upsert_document(test_doc_1)
        await neo4j_writer.upsert_document(test_doc_1)

        session = neo4j_session
        result = session.run(
            "MATCH (s:Section {doc_id: $doc_id, heading_path: $path}) RETURN count(s) as cnt",
            {"doc_id": "test-dedup-001", "path": "Main Section"},
        )
        assert result.single()["cnt"] == 1


async def test_upsert_entities_creates_entity_nodes(neo4j_session):
    """Verify upsert_entities creates Entity nodes with relationships."""
    from unittest.mock import patch

    with patch("pipeline.tasks.neo4j_writer.get_driver") as mock_get_driver:
        mock_get_driver.return_value._driver

        test_doc = {
            "file_hash": "test-entity-001",
            "filename": "test.pdf",
            "batch_id": "batch_test",
            "page_count": 1,
            "s3_key_raw": "raw/test.pdf",
            "s3_key_md": "processed/test.md",
            "chunks": [
                {
                    "chunk_id": "chunk-1",
                    "chunk_index": 0,
                    "heading_path": "Main",
                    "text": "Content about Apple Inc.",
                    "token_count": 5,
                }
            ],
        }

        await neo4j_writer.upsert_document(test_doc)

        entities = [
            {"name": "Apple Inc.", "type": "ORG", "confidence": 0.95},
            {"name": "Tim Cook", "type": "PERSON", "confidence": 0.88},
        ]

        await neo4j_writer.upsert_entities("test-entity-001", entities, [])

        session = neo4j_session
        result = session.run(
            "MATCH (e:Entity {name: $name}) RETURN e",
            {"name": "Apple Inc."},
        )
        assert result.single() is not None


async def test_upsert_entities_respects_confidence_threshold(neo4j_session, monkeypatch):
    """Verify low-confidence entities are filtered out."""
    from unittest.mock import patch
    from config.settings import settings

    monkeypatch.setattr(settings, "entity_confidence_min", 0.9)

    with patch("pipeline.tasks.neo4j_writer.get_driver") as mock_get_driver:
        mock_get_driver.return_value._driver

        test_doc = {
            "file_hash": "test-conf-001",
            "filename": "test.pdf",
            "batch_id": "batch_test",
            "page_count": 1,
            "s3_key_raw": "raw/test.pdf",
            "s3_key_md": "processed/test.md",
            "chunks": [
                {
                    "chunk_id": "chunk-1",
                    "chunk_index": 0,
                    "heading_path": "Main",
                    "text": "Content",
                    "token_count": 5,
                }
            ],
        }

        await neo4j_writer.upsert_document(test_doc)

        entities = [
            {"name": "High Confidence Org", "type": "ORG", "confidence": 0.95},
            {"name": "Low Confidence Org", "type": "ORG", "confidence": 0.85},
        ]

        await neo4j_writer.upsert_entities("test-conf-001", entities, [])

        session = neo4j_session
        result = session.run(
            "MATCH (e:Entity {name: $name}) RETURN e",
            {"name": "High Confidence Org"},
        )
        assert result.single() is not None

        result = session.run(
            "MATCH (e:Entity {name: $name}) RETURN e",
            {"name": "Low Confidence Org"},
        )
        assert result.single() is None


async def test_upsert_entities_creates_relations(neo4j_session):
    """Verify upsert_entities creates MENTIONS relationships."""
    from unittest.mock import patch

    with patch("pipeline.tasks.neo4j_writer.get_driver") as mock_get_driver:
        mock_get_driver.return_value._driver

        test_doc = {
            "file_hash": "test-rel-001",
            "filename": "test.pdf",
            "batch_id": "batch_test",
            "page_count": 1,
            "s3_key_raw": "raw/test.pdf",
            "s3_key_md": "processed/test.md",
            "chunks": [
                {
                    "chunk_id": "chunk-1",
                    "chunk_index": 0,
                    "heading_path": "Main",
                    "text": "Content",
                    "token_count": 5,
                }
            ],
        }

        await neo4j_writer.upsert_document(test_doc)

        entities = [
            {"name": "John Smith", "type": "PERSON", "confidence": 0.95},
            {"name": "Apple Inc.", "type": "ORG", "confidence": 0.95},
        ]

        relations = [
            {
                "source": "John Smith",
                "source_type": "PERSON",
                "target": "Apple Inc.",
                "target_type": "ORG",
                "relation_type": "WORKS_FOR",
                "confidence": 0.92,
            }
        ]

        await neo4j_writer.upsert_entities("test-rel-001", entities, relations)

        session = neo4j_session
        result = session.run(
            "MATCH (p:Entity {name: $name})-[r:MENTIONS]->(o:Entity {name: $org}) RETURN r",
            {"name": "John Smith", "org": "Apple Inc."},
        )
        assert result.single() is not None
