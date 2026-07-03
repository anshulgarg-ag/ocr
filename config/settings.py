from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Storage
    storage_root: str = "file:///tmp/ocr-pipeline"
    minio_endpoint: str = "http://localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"

    # PostgreSQL
    postgres_url: str = "postgresql+asyncpg://ocr:ocr@localhost:5432/ocr_pipeline"
    postgres_sync_url: str = "postgresql://ocr:ocr@localhost:5432/ocr_pipeline"

    # Qdrant
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "documents"

    # Neo4j
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "neo4jpassword"

    # GPU Provider
    gpu_provider_type: str = "self_hosted"
    gpu_ocr_url: str = "http://localhost:8001"
    gpu_embed_url: str = "http://localhost:8002"
    gpu_graph_url: str = "http://localhost:8003"

    # JarvisLabs
    jarvis_api_key: str = ""
    jarvis_instance_id: str = ""
    jarvis_host: str = ""
    jarvis_user: str = "ubuntu"
    jarvis_ssh_key_path: str = ""
    jarvis_max_runtime_hours: int = 12

    # JarvisLabs service endpoints (public IP, services bind on 0.0.0.0)
    jarvis_ocr_url: str = "http://217.18.55.79:8001"
    jarvis_embed_url: str = "http://217.18.55.79:8002"
    jarvis_graph_url: str = "http://217.18.55.79:8003"

    # Observability
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    loki_url: str = "http://localhost:3100"
    prometheus_port: int = 9090
    log_level: str = "INFO"
    log_format: str = "json"

    # Alerts
    slack_webhook_url: str = ""

    # Pipeline tuning
    ocr_workers: int = 3
    embed_batch_size: int = 64
    max_retries: int = 3
    entity_confidence_min: float = 0.6
    chunk_max_tokens: int = 1024
    chunk_overlap_tokens: int = 128

    @property
    def is_minio(self) -> bool:
        return self.storage_root.startswith("s3://")

    @property
    def storage_bucket(self) -> str:
        if self.storage_root.startswith("s3://"):
            return self.storage_root[5:].split("/")[0]
        return ""


settings = Settings()
