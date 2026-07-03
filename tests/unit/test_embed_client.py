import pytest
from unittest.mock import AsyncMock, MagicMock
from pipeline.tasks.embed_client import (
    ensure_collection,
    embed_and_upsert,
    _embed_batch,
)


async def test_ensure_collection_skips_if_exists(fake_qdrant_client, monkeypatch):
    # NB: MagicMock(name="documents") does NOT set a `.name` attribute — the
    # `name` kwarg is reserved by Mock's own constructor for its repr. Set it
    # as an attribute afterward so `.name` actually reads back "documents".
    existing_collection = MagicMock()
    existing_collection.name = "documents"
    collections_response = MagicMock()
    collections_response.collections = [existing_collection]
    fake_qdrant_client.get_collections.return_value = collections_response
    monkeypatch.setattr("pipeline.tasks.embed_client._qdrant", fake_qdrant_client)

    await ensure_collection()

    fake_qdrant_client.create_collection.assert_not_called()


async def test_ensure_collection_creates_if_missing(fake_qdrant_client, monkeypatch):
    collections_response = MagicMock()
    collections_response.collections = []
    fake_qdrant_client.get_collections.return_value = collections_response
    monkeypatch.setattr("pipeline.tasks.embed_client._qdrant", fake_qdrant_client)

    await ensure_collection()

    fake_qdrant_client.create_collection.assert_called_once()


async def test_embed_batch_posts_and_returns_embeddings(mock_embed_service):
    result = await _embed_batch(
        ["text1", "text2"],
        embed_url="http://localhost:8002"
    )

    assert "embeddings" in result or isinstance(result, list)


async def test_embed_and_upsert_single_batch(fake_qdrant_client, mock_embed_service, monkeypatch):
    monkeypatch.setattr("pipeline.tasks.embed_client._qdrant", fake_qdrant_client)
    monkeypatch.setattr("pipeline.tasks.embed_client.COLLECTION", "documents")

    chunks = [
        {
            "chunk_id": "c1",
            "doc_id": "doc1",
            "chunk_index": 0,
            "text": "Sample text",
            "heading_path": "Section",
            "token_count": 10,
        }
    ]

    result = await embed_and_upsert(chunks, embed_url="http://localhost:8002")

    assert result >= 0
    fake_qdrant_client.upsert.assert_called_once()


async def test_embed_and_upsert_respects_batch_size(fake_qdrant_client, monkeypatch):
    monkeypatch.setattr("pipeline.tasks.embed_client._qdrant", fake_qdrant_client)
    monkeypatch.setattr("pipeline.tasks.embed_client.COLLECTION", "documents")
    monkeypatch.setattr("pipeline.tasks.embed_client.settings.embed_batch_size", 2)

    httpx_mock_obj = MagicMock()

    async def mock_embed_batch(texts, embed_url=None):
        return [{"dense": [0.1] * 1024, "sparse": {}} for _ in texts]

    monkeypatch.setattr("pipeline.tasks.embed_client._embed_batch", mock_embed_batch)

    chunks = [
        {
            "chunk_id": f"c{i}",
            "doc_id": "doc1",
            "chunk_index": i,
            "text": f"Text {i}",
            "token_count": 10,
        }
        for i in range(5)
    ]

    result = await embed_and_upsert(chunks)

    assert fake_qdrant_client.upsert.call_count >= 2


async def test_embed_and_upsert_mismatched_lengths_truncates_via_zip(fake_qdrant_client, monkeypatch):
    monkeypatch.setattr("pipeline.tasks.embed_client._qdrant", fake_qdrant_client)
    monkeypatch.setattr("pipeline.tasks.embed_client.COLLECTION", "documents")

    async def mock_embed_batch(texts, embed_url=None):
        return [{"dense": [0.1] * 1024, "sparse": {}}]

    monkeypatch.setattr("pipeline.tasks.embed_client._embed_batch", mock_embed_batch)

    chunks = [
        {
            "chunk_id": "c1",
            "doc_id": "doc1",
            "chunk_index": 0,
            "text": "Text 1",
            "token_count": 10,
        },
        {
            "chunk_id": "c2",
            "doc_id": "doc1",
            "chunk_index": 1,
            "text": "Text 2",
            "token_count": 10,
        },
    ]

    result = await embed_and_upsert(chunks)

    assert result == 1
