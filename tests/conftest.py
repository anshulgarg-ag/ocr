import pytest
from pydantic_settings import SettingsConfigDict


SAMPLE_MARKDOWN = """\
# Document Title

This is a comprehensive introduction paragraph with enough content to be meaningful for testing purposes.
It contains multiple sentences to ensure we have sufficient token count for the chunker to process correctly.
The introduction explains the overall purpose and context of the document in detail.
We provide background information and set expectations for the rest of the content.

## Section 1

Content for section one with plenty of details and comprehensive information. This section has multiple sentences to test chunking behavior effectively.
The chunker should split this correctly and preserve heading context throughout the processing pipeline.
We include additional content to ensure chunks meet the minimum token threshold of fifty tokens per chunk minimum.
This section explores various aspects and provides detailed explanations for better understanding.

### Subsection 1.1

More nested content here to provide additional context and depth for testing. Entities like Apple Inc. and John Smith appear in this section.
The subsection explores technical details and implementation considerations with sufficient depth and detail.
We ensure that all sections contain enough text to meet token count requirements for proper chunking and processing.
Additional information and examples help illustrate the main concepts and ideas being presented.

## Section 2

Second section content with comprehensive information and analysis. Released on 2024-01-15 by Acme Corp according to official records.
This section includes additional sentences to ensure we meet minimum chunk size requirements consistently.
The content is structured to test heading preservation and proper section boundary detection throughout.
We provide multiple paragraphs and detailed explanations to ensure sufficient token count for embeddings.

## Section 3

Third section with detailed analysis and findings from comprehensive research. Multiple organizations including Microsoft Corp and Amazon Ltd are mentioned here.
The analysis provides comprehensive coverage of all relevant topics and considerations in the field.
Additional details ensure the chunk contains sufficient tokens for proper vector embeddings and semantic search.
We conclude with summary points and recommendations based on the analysis presented in this section.
"""


@pytest.fixture
def sample_markdown() -> str:
    return SAMPLE_MARKDOWN


@pytest.fixture
def mock_ocr_service(httpx_mock):
    # ocr_client.ocr_document/ocr_batch never call GET /health themselves
    # (that endpoint is only polled by the GPU provider's wait_for_services);
    # registering it here left httpx_mock complaining at teardown that a
    # mocked response was never requested.
    httpx_mock.add_response(
        method="POST",
        url="http://localhost:8001/ocr",
        json={
            "doc_id": "test-doc-001",
            "page_count": 3,
            "duration_ms": 850.0,
            "s3_key_md": "processed/test-doc.md",
        },
        is_reusable=True,
    )
    return httpx_mock


@pytest.fixture
def mock_embed_service(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="http://localhost:8002/embed",
        json={
            "embeddings": [
                {
                    "dense": [0.1] * 1024,
                    "sparse": {"indices": [1, 5, 10], "values": [0.5, 0.3, 0.2]},
                }
            ]
        },
    )
    return httpx_mock


@pytest.fixture
def mock_graph_service(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="http://localhost:8003/extract",
        json={
            "doc_id": "test-doc-001",
            "entities": [
                {"name": "Apple Inc.", "type": "ORG", "confidence": 0.95},
                {"name": "John Smith", "type": "PERSON", "confidence": 0.88},
            ],
            "relations": [
                {
                    "source": "John Smith",
                    "source_type": "PERSON",
                    "target": "Apple Inc.",
                    "target_type": "ORG",
                    "relation_type": "WORKS_FOR",
                    "confidence": 0.92,
                }
            ],
            "duration_ms": 1200.0,
        },
    )
    return httpx_mock


@pytest.fixture(autouse=True)
def isolate_settings_from_dotenv(monkeypatch):
    """Prevent config.settings.Settings() from reading the real repo .env file.

    The real .env at the repo root sets values (e.g. STORAGE_ROOT=s3://ocr-pipeline)
    that differ from the code-level defaults in config/settings.py. Without this
    fixture, a bare `Settings()` call in tests would silently pick those up via
    pydantic-settings' env_file loading, breaking tests that assert default values.
    """
    from config.settings import Settings

    monkeypatch.setattr(
        Settings,
        "model_config",
        SettingsConfigDict(env_file=None, env_file_encoding="utf-8", extra="ignore"),
    )

    env_keys = [
        "STORAGE_ROOT", "MINIO_ENDPOINT", "MINIO_ACCESS_KEY", "MINIO_SECRET_KEY",
        "POSTGRES_URL", "POSTGRES_SYNC_URL",
        "QDRANT_URL", "QDRANT_COLLECTION",
        "NEO4J_URI", "NEO4J_USERNAME", "NEO4J_USER", "NEO4J_PASSWORD",
        "NEO4J_DATABASE", "AURA_INSTANCEID",
        "GPU_PROVIDER_TYPE", "GPU_OCR_URL", "GPU_EMBED_URL", "GPU_GRAPH_URL",
        "JARVIS_API_KEY", "JARVIS_INSTANCE_ID", "JARVIS_HOST", "JARVIS_USER",
        "JARVIS_SSH_KEY_PATH", "JARVIS_MAX_RUNTIME_HOURS",
        "JARVIS_OCR_URL", "JARVIS_EMBED_URL", "JARVIS_GRAPH_URL",
        "OTEL_EXPORTER_OTLP_ENDPOINT", "LOKI_URL", "PROMETHEUS_PORT",
        "LOG_LEVEL", "LOG_FORMAT",
        "SLACK_WEBHOOK_URL",
        "OCR_WORKERS", "EMBED_BATCH_SIZE", "MAX_RETRIES", "ENTITY_CONFIDENCE_MIN",
        "CHUNK_MAX_TOKENS", "CHUNK_OVERLAP_TOKENS",
        "HF_TOKEN",
    ]
    for key in env_keys:
        monkeypatch.delenv(key, raising=False)

    yield


def pytest_configure(config):
    import asyncio
    import sys
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.fixture
def fake_session():
    from unittest.mock import AsyncMock
    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    return session


@pytest.fixture
def fake_neo4j_driver():
    from unittest.mock import AsyncMock, MagicMock
    driver = AsyncMock()
    session_obj = MagicMock()
    session_obj.__aenter__ = AsyncMock(return_value=session_obj)
    session_obj.__aexit__ = AsyncMock(return_value=None)
    session_obj.run = AsyncMock()
    driver.session = MagicMock(return_value=session_obj)
    return driver


@pytest.fixture
def fake_qdrant_client():
    from unittest.mock import AsyncMock, MagicMock
    client = AsyncMock()
    client.get_collections = AsyncMock(return_value=MagicMock(collections=[]))
    client.create_collection = AsyncMock()
    client.upsert = AsyncMock()
    return client


@pytest.fixture(autouse=True)
def reset_module_singletons(monkeypatch):
    yield
    try:
        import pipeline.tasks.embed_client
        monkeypatch.setattr(pipeline.tasks.embed_client, "_qdrant", None)
    except (ImportError, AttributeError):
        pass
    try:
        import pipeline.tasks.neo4j_writer
        monkeypatch.setattr(pipeline.tasks.neo4j_writer, "_driver", None)
    except (ImportError, AttributeError):
        pass
    try:
        import pipeline.tasks.jarvis_ops
        monkeypatch.setattr(pipeline.tasks.jarvis_ops, "_tunnel_proc", None)
    except (ImportError, AttributeError):
        pass
    try:
        import pipeline.flows.batch_ingest
        monkeypatch.setattr(pipeline.flows.batch_ingest, "_provider", None)
    except (ImportError, AttributeError):
        pass
