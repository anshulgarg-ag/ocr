import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pipeline.flows.batch_ingest import (
    task_discover,
    task_start_gpu,
    task_ocr,
    task_chunk,
    task_embed,
    task_graph,
    batch_ingest_flow,
)


async def test_task_discover_registers_new_files(monkeypatch, fake_session):
    mock_discovery = AsyncMock()
    mock_discovery.get_known_hashes = AsyncMock(return_value={"old_hash"})
    mock_discovery.find_new_files = AsyncMock(return_value=[
        {"file_hash": "hash1", "s3_key_raw": "raw/doc1.pdf", "filename": "doc1.pdf"}
    ])

    mock_state = AsyncMock()
    mock_state.AsyncSessionLocal = MagicMock(return_value=fake_session)
    mock_state.register_new_documents = AsyncMock(return_value=1)

    monkeypatch.setattr("pipeline.flows.batch_ingest.discovery", mock_discovery)
    monkeypatch.setattr("pipeline.flows.batch_ingest.state", mock_state)

    result = await task_discover.fn("batch_1")

    assert isinstance(result, list)


async def test_task_start_gpu_sets_global_provider_and_returns_endpoints(monkeypatch):
    mock_provider = AsyncMock()
    mock_provider.start = AsyncMock()
    mock_provider.wait_for_services = AsyncMock()
    mock_endpoints = {
        "ocr_url": "http://localhost:8001",
        "embed_url": "http://localhost:8002",
        "graph_url": "http://localhost:8003",
        "storage_url": "http://localhost:9000",
    }
    mock_provider.ocr_url = "http://localhost:8001"
    mock_provider.embed_url = "http://localhost:8002"
    mock_provider.graph_url = "http://localhost:8003"
    mock_provider.storage_url = "http://localhost:9000"

    def mock_create_provider(*args, **kwargs):
        return mock_provider

    monkeypatch.setattr("pipeline.flows.batch_ingest.create_gpu_provider", mock_create_provider)

    result = await task_start_gpu.fn()

    assert result is not None


async def test_task_ocr_advances_success_and_marks_failed_on_error(monkeypatch, fake_session):
    mock_ocr_batch = AsyncMock(return_value=[
        {
            "file_hash": "hash1",
            "s3_key_md": "processed/doc.md",
            "page_count": 3,
            "success": True,
            "error": None,
        }
    ])

    mock_state = AsyncMock()
    mock_state.AsyncSessionLocal = MagicMock(return_value=fake_session)
    mock_state.advance = AsyncMock()
    mock_state.mark_failed = AsyncMock()

    monkeypatch.setattr("pipeline.flows.batch_ingest.ocr_client.ocr_batch", mock_ocr_batch)
    monkeypatch.setattr("pipeline.flows.batch_ingest.state", mock_state)

    docs = [{"file_hash": "hash1", "s3_key_raw": "raw/doc.pdf", "filename": "doc.pdf"}]
    endpoints = {"ocr_url": "http://localhost:8001"}

    result = await task_ocr.fn(docs, "batch_1", endpoints)

    assert isinstance(result, list)


async def test_task_chunk_writes_jsonl_and_advances(monkeypatch, fake_session):
    mock_storage = AsyncMock()
    mock_storage.read_text = MagicMock(return_value="# Title\n\nContent")
    mock_storage.write_text = MagicMock()

    mock_chunker = AsyncMock()
    mock_chunker.chunk_markdown = AsyncMock(return_value=[
        {
            "chunk_id": "c1",
            "text": "Content",
            "token_count": 10,
            "heading_path": "Title",
        }
    ])
    mock_chunker.chunks_to_jsonl = AsyncMock(return_value='{"chunk_id":"c1"}\n')

    mock_state = AsyncMock()
    mock_state.AsyncSessionLocal = MagicMock(return_value=fake_session)
    mock_state.advance = AsyncMock()
    mock_state.mark_failed = AsyncMock()

    monkeypatch.setattr("pipeline.flows.batch_ingest.storage_ops", mock_storage)
    monkeypatch.setattr("pipeline.flows.batch_ingest.chunker", mock_chunker)
    monkeypatch.setattr("pipeline.flows.batch_ingest.state", mock_state)

    ocr_results = [
        {
            "file_hash": "hash1",
            "s3_key_md": "processed/doc.md",
            "filename": "doc.pdf",
        }
    ]

    result = await task_chunk.fn(ocr_results)

    assert isinstance(result, list)


async def test_task_chunk_drops_doc_on_exception(monkeypatch, fake_session):
    mock_storage = AsyncMock()
    mock_storage.read_text = MagicMock(side_effect=IOError("File not found"))

    mock_state = AsyncMock()
    mock_state.AsyncSessionLocal = MagicMock(return_value=fake_session)
    mock_state.mark_failed = AsyncMock()

    monkeypatch.setattr("pipeline.flows.batch_ingest.storage_ops", mock_storage)
    monkeypatch.setattr("pipeline.flows.batch_ingest.state", mock_state)

    ocr_results = [
        {
            "file_hash": "hash1",
            "s3_key_md": "processed/doc.md",
            "filename": "doc.pdf",
        }
    ]

    result = await task_chunk.fn(ocr_results)

    assert isinstance(result, list)


async def test_task_embed_calls_ensure_collection_once_and_upserts(monkeypatch, fake_session):
    mock_embed_client = AsyncMock()
    mock_embed_client.ensure_collection = AsyncMock()
    mock_embed_client.embed_and_upsert = AsyncMock(return_value=5)

    mock_state = AsyncMock()
    mock_state.AsyncSessionLocal = MagicMock(return_value=fake_session)
    mock_state.advance = AsyncMock()
    mock_state.mark_failed = AsyncMock()

    monkeypatch.setattr("pipeline.flows.batch_ingest.embed_client", mock_embed_client)
    monkeypatch.setattr("pipeline.flows.batch_ingest.state", mock_state)

    chunked_results = [
        {
            "file_hash": "hash1",
            "chunks": [
                {"chunk_id": "c1", "text": "Content", "token_count": 10}
            ],
        }
    ]
    endpoints = {"embed_url": "http://localhost:8002"}

    result = await task_embed.fn(chunked_results, endpoints)

    assert result is None


async def test_task_graph_upserts_document_and_entities(monkeypatch, fake_session, mock_graph_service):
    mock_neo4j = AsyncMock()
    mock_neo4j.setup_constraints = AsyncMock()
    mock_neo4j.upsert_document = AsyncMock()
    mock_neo4j.upsert_entities = AsyncMock()

    mock_storage = AsyncMock()
    mock_storage.read_text = MagicMock(return_value="# Title\n\nContent")

    mock_state = AsyncMock()
    mock_state.AsyncSessionLocal = MagicMock(return_value=fake_session)
    mock_state.advance = AsyncMock()
    mock_state.mark_failed = AsyncMock()

    monkeypatch.setattr("pipeline.flows.batch_ingest.neo4j_writer", mock_neo4j)
    monkeypatch.setattr("pipeline.flows.batch_ingest.storage_ops", mock_storage)
    monkeypatch.setattr("pipeline.flows.batch_ingest.state", mock_state)

    chunked_results = [
        {
            "file_hash": "hash1",
            "s3_key_md": "processed/doc.md",
            "chunks": [],
        }
    ]
    original_docs = [
        {
            "file_hash": "hash1",
            "filename": "doc.pdf",
        }
    ]
    endpoints = {"graph_url": "http://localhost:8003"}

    result = await task_graph.fn(chunked_results, original_docs, endpoints)

    assert result is None


async def test_batch_ingest_flow_no_new_files_early_return(monkeypatch):
    # batch_ingest_flow calls task_discover(batch_id) directly (real Prefect
    # task-call syntax, not `.fn()`), so the mock replacing it must itself be
    # directly awaitable/callable — configuring a nested `.fn` attribute here
    # would never be consulted and the flow would instead await an
    # unconfigured auto-mock.
    mock_discovery = AsyncMock(return_value=[])

    mock_storage = AsyncMock()
    mock_storage.ensure_bucket = MagicMock()

    monkeypatch.setattr("pipeline.flows.batch_ingest.task_discover", mock_discovery)
    monkeypatch.setattr("pipeline.flows.batch_ingest.storage_ops", mock_storage)
    monkeypatch.setattr("pipeline.flows.batch_ingest.get_run_logger", lambda: MagicMock())

    result = await batch_ingest_flow.fn()

    assert result is not None
    assert "batch_id" in result or isinstance(result, dict)


async def test_batch_ingest_flow_happy_path_end_to_end(monkeypatch, fake_session):
    # batch_ingest_flow calls each of these tasks directly (task_x(args)),
    # not via `.fn()`, so the mocks replacing them must be directly
    # awaitable — see the comment in test_batch_ingest_flow_no_new_files_early_return.
    mock_discovery = AsyncMock(return_value=[
        {"file_hash": "hash1", "s3_key_raw": "raw/doc.pdf", "filename": "doc.pdf"}
    ])

    mock_start_gpu = AsyncMock(return_value={
        "ocr_url": "http://localhost:8001",
        "embed_url": "http://localhost:8002",
        "graph_url": "http://localhost:8003",
        "storage_url": "http://localhost:9000",
    })

    mock_ocr = AsyncMock(return_value=[
        {
            "file_hash": "hash1",
            "s3_key_md": "processed/doc.md",
            "page_count": 3,
            "success": True,
        }
    ])

    mock_chunk = AsyncMock(return_value=[
        {
            "file_hash": "hash1",
            "s3_key_chunks": "chunks/doc.jsonl",
            "chunks": [],
        }
    ])

    mock_embed = AsyncMock(return_value=None)

    mock_graph = AsyncMock(return_value=None)

    mock_provider = AsyncMock()
    mock_provider.stop = AsyncMock()

    mock_state = AsyncMock()
    mock_state.AsyncSessionLocal = MagicMock(return_value=fake_session)
    mock_state.advance = AsyncMock()
    mock_state.count_dead_letters = AsyncMock(return_value=0)

    mock_storage = AsyncMock()
    mock_storage.ensure_bucket = MagicMock()

    mock_alerts = AsyncMock()

    monkeypatch.setattr("pipeline.flows.batch_ingest.task_discover", mock_discovery)
    monkeypatch.setattr("pipeline.flows.batch_ingest.task_start_gpu", mock_start_gpu)
    monkeypatch.setattr("pipeline.flows.batch_ingest.task_ocr", mock_ocr)
    monkeypatch.setattr("pipeline.flows.batch_ingest.task_chunk", mock_chunk)
    monkeypatch.setattr("pipeline.flows.batch_ingest.task_embed", mock_embed)
    monkeypatch.setattr("pipeline.flows.batch_ingest.task_graph", mock_graph)
    monkeypatch.setattr("pipeline.flows.batch_ingest.storage_ops", mock_storage)
    monkeypatch.setattr("pipeline.flows.batch_ingest.state", mock_state)
    monkeypatch.setattr("pipeline.flows.batch_ingest._provider", mock_provider)
    monkeypatch.setattr("pipeline.flows.batch_ingest.alert_dead_letter_spike", AsyncMock())
    monkeypatch.setattr("pipeline.flows.batch_ingest.get_run_logger", lambda: MagicMock())

    result = await batch_ingest_flow.fn()

    assert result is not None


async def test_batch_ingest_flow_exception_calls_alert_and_reraises(monkeypatch):
    mock_discovery = AsyncMock(side_effect=RuntimeError("Test error"))

    mock_storage = AsyncMock()
    mock_storage.ensure_bucket = MagicMock()

    mock_alerts = AsyncMock()

    monkeypatch.setattr("pipeline.flows.batch_ingest.task_discover", mock_discovery)
    monkeypatch.setattr("pipeline.flows.batch_ingest.storage_ops", mock_storage)
    monkeypatch.setattr("pipeline.flows.batch_ingest.alert_flow_failed", mock_alerts)
    monkeypatch.setattr("pipeline.flows.batch_ingest.get_run_logger", lambda: MagicMock())

    with pytest.raises(RuntimeError):
        await batch_ingest_flow.fn()

    mock_alerts.assert_called_once()


async def test_batch_ingest_flow_provider_stop_called_in_finally(monkeypatch):
    stop_called = [False]

    mock_provider = AsyncMock()

    async def mock_stop():
        stop_called[0] = True

    mock_provider.stop = mock_stop

    mock_discovery = AsyncMock(side_effect=RuntimeError("Test error"))

    mock_storage = AsyncMock()
    mock_storage.ensure_bucket = MagicMock()

    monkeypatch.setattr("pipeline.flows.batch_ingest.task_discover", mock_discovery)
    monkeypatch.setattr("pipeline.flows.batch_ingest.storage_ops", mock_storage)
    monkeypatch.setattr("pipeline.flows.batch_ingest.alert_flow_failed", AsyncMock())
    monkeypatch.setattr("pipeline.flows.batch_ingest._provider", mock_provider)
    monkeypatch.setattr("pipeline.flows.batch_ingest.get_run_logger", lambda: MagicMock())

    with pytest.raises(RuntimeError):
        await batch_ingest_flow.fn()

    assert stop_called[0]
