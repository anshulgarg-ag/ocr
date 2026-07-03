"""Integration test fixtures for real docker-compose services."""
import os
import socket
import asyncio
import uuid
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
from neo4j import GraphDatabase
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models


def is_port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    """Check if a port is open and accepting connections."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        result = sock.connect_ex((host, port))
        return result == 0
    finally:
        sock.close()


@pytest.fixture(scope="session", autouse=True)
def skip_if_docker_unavailable():
    """Skip all integration tests if docker services are not running."""
    services = {
        "postgres": ("localhost", 5432),
        "neo4j": ("localhost", 7687),
        "qdrant": ("localhost", 6333),
        "minio": ("localhost", 9000),
    }

    unavailable = []
    for name, (host, port) in services.items():
        if not is_port_open(host, port, timeout=0.5):
            unavailable.append(f"{name} ({host}:{port})")

    if unavailable:
        pytest.skip(
            f"Docker services not available. Start them with:\n"
            f"  docker-compose -f infra/docker-compose.yml up -d "
            f"postgres qdrant neo4j minio\n"
            f"Unavailable: {', '.join(unavailable)}"
        )


@pytest_asyncio.fixture(scope="session")
async def pg_engine():
    """Create an async SQLAlchemy engine for PostgreSQL."""
    engine = create_async_engine(
        "postgresql+asyncpg://ocr:ocr@localhost:5432/ocr_pipeline",
        echo=False,
    )

    async with engine.begin() as conn:
        await conn.run_sync(_create_postgres_schema)

    yield engine

    await engine.dispose()


def _create_postgres_schema(sync_conn):
    """Create the schema in PostgreSQL."""
    schema_sql = """
    DROP TYPE IF EXISTS doc_status CASCADE;

    CREATE TYPE doc_status AS ENUM (
        'pending',
        'ocr_done',
        'chunked',
        'embedded',
        'graph_done',
        'complete',
        'failed',
        'dead_letter'
    );

    CREATE TABLE IF NOT EXISTS documents (
        file_hash        VARCHAR(64) PRIMARY KEY,
        s3_key_raw       TEXT NOT NULL,
        s3_key_md        TEXT,
        s3_key_chunks    TEXT,
        batch_id         VARCHAR(64) NOT NULL,
        status           doc_status NOT NULL DEFAULT 'pending',
        retry_count      SMALLINT NOT NULL DEFAULT 0,
        error_msg        TEXT,
        page_count       INTEGER,
        created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);
    CREATE INDEX IF NOT EXISTS idx_documents_batch_id ON documents(batch_id);
    CREATE INDEX IF NOT EXISTS idx_documents_updated_at ON documents(updated_at);

    CREATE TABLE IF NOT EXISTS failed_documents (
        id               SERIAL PRIMARY KEY,
        file_hash        VARCHAR(64) NOT NULL REFERENCES documents(file_hash),
        failed_stage     TEXT NOT NULL,
        last_error       TEXT NOT NULL,
        failed_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        manual_review    BOOLEAN NOT NULL DEFAULT FALSE,
        notes            TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_failed_manual_review
        ON failed_documents(manual_review) WHERE manual_review = FALSE;

    CREATE OR REPLACE FUNCTION update_updated_at()
    RETURNS TRIGGER AS $$
    BEGIN
        NEW.updated_at = NOW();
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;

    DROP TRIGGER IF EXISTS documents_updated_at ON documents;
    CREATE TRIGGER documents_updated_at
        BEFORE UPDATE ON documents
        FOR EACH ROW EXECUTE FUNCTION update_updated_at();
    """
    sync_conn.execute(text(schema_sql))
    sync_conn.commit()


@pytest_asyncio.fixture
async def pg_session(pg_engine):
    """Provide an async SQLAlchemy session for each test, with cleanup."""
    async_session_maker = sessionmaker(
        pg_engine, class_=AsyncSession, expire_on_commit=False
    )

    async with async_session_maker() as session:
        yield session

        await session.rollback()

    async with async_session_maker() as cleanup_session:
        await cleanup_session.execute(text("DELETE FROM failed_documents"))
        await cleanup_session.execute(text("DELETE FROM documents"))
        await cleanup_session.commit()


@pytest.fixture(scope="session")
def neo4j_driver():
    """Create a Neo4j driver for the session."""
    driver = GraphDatabase.driver(
        "bolt://localhost:7687",
        auth=("neo4j", "neo4jpassword"),
    )
    yield driver
    driver.close()


@pytest.fixture
def neo4j_session(neo4j_driver):
    """Provide a Neo4j session for each test, with cleanup."""
    session = neo4j_driver.session()

    session.run(
        "CREATE CONSTRAINT IF NOT EXISTS FOR (d:Document) REQUIRE d.id IS UNIQUE"
    )
    session.run(
        "CREATE CONSTRAINT IF NOT EXISTS FOR (s:Section) REQUIRE s.id IS UNIQUE"
    )
    session.run(
        "CREATE CONSTRAINT IF NOT EXISTS FOR (c:Chunk) REQUIRE c.id IS UNIQUE"
    )
    session.run(
        "CREATE CONSTRAINT IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE"
    )

    yield session

    try:
        session.run("MATCH (n) WHERE n.id STARTS WITH 'test-' DETACH DELETE n")
    finally:
        session.close()


@pytest_asyncio.fixture
async def qdrant_client():
    """Provide a real AsyncQdrantClient connected to local Qdrant."""
    client = AsyncQdrantClient(url="http://localhost:6333")

    collection_name = f"test_{uuid.uuid4().hex[:8]}"

    try:
        await client.create_collection(
            collection_name=collection_name,
            vectors_config=models.VectorParams(
                size=1024,
                distance=models.Distance.COSINE,
            ),
            sparse_vectors_config={
                "sparse": models.SparseVectorParams(
                    index=models.SparseIndexParams(on_disk=False)
                )
            },
        )
    except Exception:
        pass

    yield client, collection_name

    try:
        await client.delete_collection(collection_name=collection_name)
    except Exception:
        pass


@pytest.fixture
def minio_settings(monkeypatch):
    """Configure storage_ops to use local MinIO."""
    monkeypatch.setenv("MINIO_ENDPOINT", "http://localhost:9000")
    monkeypatch.setenv("MINIO_ACCESS_KEY", "minioadmin")
    monkeypatch.setenv("MINIO_SECRET_KEY", "minioadmin")

    from config.settings import settings
    monkeypatch.setattr(settings, "storage_root", "s3://ocr-pipeline/test")
    monkeypatch.setattr(settings, "minio_endpoint", "http://localhost:9000")
    monkeypatch.setattr(settings, "minio_access_key", "minioadmin")
    monkeypatch.setattr(settings, "minio_secret_key", "minioadmin")

    import pipeline.tasks.storage_ops
    pipeline.tasks.storage_ops._fs_cache.clear()
    monkeypatch.setattr(pipeline.tasks.storage_ops, "_fs_cache", {})

    yield

    pipeline.tasks.storage_ops._fs_cache.clear()
    monkeypatch.setattr(pipeline.tasks.storage_ops, "_fs_cache", {})
