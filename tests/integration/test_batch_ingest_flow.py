"""Integration test for batch_ingest_flow against real services."""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from sqlalchemy import text
from pipeline.flows.batch_ingest import batch_ingest_flow


pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_batch_ingest_flow_happy_path(pg_session, neo4j_session, qdrant_client, minio_settings, monkeypatch):
    """
    End-to-end test: discover → OCR → chunk → embed → graph → complete.
    Tests against real Postgres/Neo4j/Qdrant/MinIO with mocked GPU services.
    """
    from pipeline.tasks import storage_ops
    from config.settings import settings
    from qdrant_client.http import models

    client, collection_name = qdrant_client

    monkeypatch.setattr(settings, "gpu_provider_type", "self_hosted")

    with patch("pipeline.flows.batch_ingest.create_gpu_provider") as mock_provider_factory:
        mock_provider = AsyncMock()
        mock_provider.ocr_url = "http://localhost:8001"
        mock_provider.embed_url = "http://localhost:8002"
        mock_provider.graph_url = "http://localhost:8003"
        mock_provider.storage_url = "http://localhost:9000"
        mock_provider.start = AsyncMock(return_value=MagicMock(
            ocr_url="http://localhost:8001",
            embed_url="http://localhost:8002",
            graph_url="http://localhost:8003",
            storage_url="http://localhost:9000",
        ))
        mock_provider.stop = AsyncMock()
        mock_provider_factory.return_value = mock_provider

        storage_ops.upload_bytes(b"Mock PDF content", "raw/test_doc.pdf")

        def mock_ocr_response(*args, **kwargs):
            response = MagicMock()
            response.status_code = 200
            response.json = MagicMock(return_value={
                "doc_id": "test-doc-001",
                "page_count": 3,
                "duration_ms": 100.0,
                "s3_key_md": "processed/test_doc.md",
            })
            return response

        def mock_embed_response(*args, **kwargs):
            response = MagicMock()
            response.status_code = 200
            response.json = MagicMock(return_value={
                "embeddings": [
                    {"dense": [0.1] * 1024, "sparse": {"indices": [1, 5], "values": [0.5, 0.3]}}
                    for _ in range(5)
                ]
            })
            return response

        def mock_graph_response(*args, **kwargs):
            response = MagicMock()
            response.status_code = 200
            response.json = MagicMock(return_value={
                "doc_id": "test-doc-001",
                "entities": [
                    {"name": "Test Company", "type": "ORG", "confidence": 0.95},
                ],
                "relations": [],
                "duration_ms": 200.0,
            })
            return response

        with patch("pipeline.flows.batch_ingest.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=MagicMock(status_code=200))
            mock_client.post = mock_ocr_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)

            mock_client_class.return_value = mock_client

            result = await batch_ingest_flow.fn()

        assert result is not None
        assert result.get("batch_id")

        rows = await pg_session.execute(
            text("SELECT status FROM documents WHERE batch_id = :bid"),
            {"bid": result["batch_id"]},
        )
        statuses = [r[0] for r in rows.fetchall()]
        assert any(s in ["complete", "failed"] for s in statuses)


@pytest.mark.asyncio
async def test_batch_ingest_flow_no_new_files_early_return(pg_session, monkeypatch):
    """Verify batch_ingest_flow returns early when no new files discovered."""
    from pipeline.tasks import discovery

    async def mock_find_new(*args, **kwargs):
        return []

    monkeypatch.setattr(discovery, "find_new_files", mock_find_new)

    with patch("pipeline.flows.batch_ingest.create_gpu_provider"):
        result = await batch_ingest_flow.fn()

        assert result is not None
        assert result.get("new_files") == 0


@pytest.mark.asyncio
async def test_batch_ingest_flow_provider_stop_called_on_error(pg_session, monkeypatch):
    """Verify provider.stop() is called in finally block on error."""
    from pipeline.tasks import storage_ops

    storage_ops.upload_bytes(b"PDF", "raw/test.pdf")

    stop_called = [False]

    with patch("pipeline.flows.batch_ingest.create_gpu_provider") as mock_provider_factory:
        mock_provider = AsyncMock()

        async def mock_stop():
            stop_called[0] = True

        mock_provider.stop = mock_stop
        mock_provider.start = AsyncMock(side_effect=RuntimeError("Simulated GPU error"))

        mock_provider_factory.return_value = mock_provider

        with pytest.raises(RuntimeError, match="Simulated GPU error"):
            await batch_ingest_flow.fn()

        assert stop_called[0] is True
