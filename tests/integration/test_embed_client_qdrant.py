"""Integration tests for embed_client.py against real Qdrant."""
import pytest
from qdrant_client.http import models
from pipeline.tasks import embed_client


pytestmark = pytest.mark.integration


async def test_ensure_collection_creates_with_correct_vector_params(qdrant_client):
    """Verify ensure_collection creates collection with correct vector params."""
    client, collection_name = qdrant_client

    from unittest.mock import patch

    with patch("pipeline.tasks.embed_client._qdrant", client):
        with patch("pipeline.tasks.embed_client.COLLECTION", collection_name):
            await embed_client.ensure_collection()

    collections = await client.get_collections()
    collection_names = {c.name for c in collections.collections}
    assert collection_name in collection_names

    collection_info = await client.get_collection(collection_name)
    assert collection_info.config.vectors.size == 1024
    assert collection_info.config.vectors.distance == models.Distance.COSINE

    assert "sparse" in collection_info.config.sparse_vectors


async def test_embed_and_upsert_points_are_queryable(qdrant_client, monkeypatch):
    """Verify upserted points can be queried from Qdrant."""
    from unittest.mock import patch, AsyncMock

    client, collection_name = qdrant_client

    with patch("pipeline.tasks.embed_client._qdrant", client):
        with patch("pipeline.tasks.embed_client.COLLECTION", collection_name):
            await embed_client.ensure_collection()

            deterministic_embeddings = [
                {"dense": [0.1] * 1024, "sparse": {"indices": [1, 5], "values": [0.5, 0.3]}}
                for _ in range(2)
            ]

            async def mock_embed_batch(texts, embed_url=None):
                return deterministic_embeddings[: len(texts)]

            with patch("pipeline.tasks.embed_client._embed_batch", side_effect=mock_embed_batch):
                chunks = [
                    {
                        "chunk_id": "test-chunk-1",
                        "doc_id": "test-doc-001",
                        "chunk_index": 0,
                        "text": "First chunk text",
                        "heading_path": "Section 1",
                        "token_count": 10,
                    },
                    {
                        "chunk_id": "test-chunk-2",
                        "doc_id": "test-doc-001",
                        "chunk_index": 1,
                        "text": "Second chunk text",
                        "heading_path": "Section 1 > Subsection",
                        "token_count": 12,
                    },
                ]

                count = await embed_client.embed_and_upsert(chunks)
                assert count == 2

                scroll_result = await client.scroll(
                    collection_name=collection_name,
                    limit=10,
                    with_payload=True,
                    with_vectors=False,
                )

                points, _ = scroll_result
                assert len(points) == 2

                payloads = [p.payload for p in points]
                doc_ids = {p["doc_id"] for p in payloads}
                assert "test-doc-001" in doc_ids


async def test_ensure_collection_skips_if_exists(qdrant_client):
    """Verify ensure_collection skips creation if collection already exists."""
    client, collection_name = qdrant_client

    from unittest.mock import patch, AsyncMock

    with patch("pipeline.tasks.embed_client._qdrant", client):
        with patch("pipeline.tasks.embed_client.COLLECTION", collection_name):
            await embed_client.ensure_collection()

            create_spy = AsyncMock()
            original_create = client.create_collection

            async def create_and_spy(*args, **kwargs):
                create_spy(*args, **kwargs)
                return await original_create(*args, **kwargs)

            client.create_collection = create_and_spy

            await embed_client.ensure_collection()

            assert create_spy.call_count == 0
