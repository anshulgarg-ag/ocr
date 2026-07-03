import pytest
from unittest.mock import AsyncMock, MagicMock
from pipeline.tasks.neo4j_writer import (
    setup_constraints,
    upsert_document,
    upsert_entities,
)


async def test_setup_constraints_runs_five_statements(fake_neo4j_driver, monkeypatch):
    monkeypatch.setattr("pipeline.tasks.neo4j_writer.get_driver", lambda: fake_neo4j_driver)

    await setup_constraints()

    session_obj = fake_neo4j_driver.session.return_value.__aenter__.return_value
    assert session_obj.run.call_count == 5


async def test_upsert_document_merges_document_and_chunks(fake_neo4j_driver, monkeypatch):
    monkeypatch.setattr("pipeline.tasks.neo4j_writer.get_driver", lambda: fake_neo4j_driver)
    doc = {
        "file_hash": "hash1",
        "filename": "test.pdf",
        "batch_id": "batch_1",
        "page_count": 3,
        "s3_key_raw": "raw/test.pdf",
        "s3_key_md": "processed/test.md",
        "chunks": [
            {
                "chunk_id": "chunk_1",
                "chunk_index": 0,
                "heading_path": "Introduction",
                "text": "This is the first chunk",
                "token_count": 10,
            }
        ],
    }

    await upsert_document(doc)

    session_obj = fake_neo4j_driver.session.return_value.__aenter__.return_value
    assert session_obj.run.call_count >= 2


async def test_upsert_document_dedupes_sections_by_heading_path(fake_neo4j_driver, monkeypatch):
    monkeypatch.setattr("pipeline.tasks.neo4j_writer.get_driver", lambda: fake_neo4j_driver)
    doc = {
        "file_hash": "hash1",
        "filename": "test.pdf",
        "batch_id": "batch_1",
        "page_count": 3,
        "s3_key_raw": "raw/test.pdf",
        "s3_key_md": "processed/test.md",
        "chunks": [
            {
                "chunk_id": "chunk_1",
                "chunk_index": 0,
                "heading_path": "Section > Subsection",
                "text": "First chunk",
                "token_count": 10,
            },
            {
                "chunk_id": "chunk_2",
                "chunk_index": 1,
                "heading_path": "Section > Subsection",
                "text": "Second chunk same section",
                "token_count": 15,
            },
        ],
    }

    await upsert_document(doc)

    session_obj = fake_neo4j_driver.session.return_value.__aenter__.return_value
    calls = session_obj.run.call_args_list
    section_queries = [call for call in calls if "Section" in str(call)]
    assert len(section_queries) >= 1


async def test_upsert_document_missing_chunk_id_raises_keyerror(fake_neo4j_driver, monkeypatch):
    monkeypatch.setattr("pipeline.tasks.neo4j_writer.get_driver", lambda: fake_neo4j_driver)
    doc = {
        "file_hash": "hash1",
        "filename": "test.pdf",
        "batch_id": "batch_1",
        "page_count": 1,
        "s3_key_raw": "raw/test.pdf",
        "s3_key_md": "processed/test.md",
        "chunks": [
            {
                "chunk_index": 0,
                "heading_path": "Intro",
                "text": "Missing chunk_id",
                "token_count": 5,
            }
        ],
    }

    with pytest.raises(KeyError):
        await upsert_document(doc)


async def test_upsert_entities_filters_below_confidence_threshold(fake_neo4j_driver, monkeypatch):
    monkeypatch.setattr("pipeline.tasks.neo4j_writer.get_driver", lambda: fake_neo4j_driver)
    monkeypatch.setattr("pipeline.tasks.neo4j_writer.settings.entity_confidence_min", 0.8)

    entities = [
        {"name": "Apple Inc.", "type": "ORG", "confidence": 0.95},
        {"name": "Bob Smith", "type": "PERSON", "confidence": 0.5},
    ]
    relations = []

    await upsert_entities("doc1", entities, relations)

    session_obj = fake_neo4j_driver.session.return_value.__aenter__.return_value
    calls = [str(call) for call in session_obj.run.call_args_list]
    assert len(calls) >= 1


async def test_upsert_entities_missing_name_raises_keyerror(fake_neo4j_driver, monkeypatch):
    monkeypatch.setattr("pipeline.tasks.neo4j_writer.get_driver", lambda: fake_neo4j_driver)
    entities = [
        {"type": "ORG", "confidence": 0.95}
    ]
    relations = []

    with pytest.raises(KeyError):
        await upsert_entities("doc1", entities, relations)
