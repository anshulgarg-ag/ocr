# Chandra OCR Pipeline

GPU-accelerated document ingestion pipeline: PDF/image → OCR → vector embeddings + knowledge graph.

---

## What It Targets

Converts unstructured documents (PDFs, scanned images) into a queryable hybrid knowledge base combining:
- **Semantic vector search** (Qdrant, BGE-M3 embeddings)
- **Structured knowledge graph** (Neo4j, entity/relation extraction)

Use case: enterprise document intelligence — ingest large document corpora and query them via natural language or graph traversal.

---

## System Design

```
┌─────────────────────────────────────────────────────────┐
│  Local Machine                                           │
│                                                          │
│  ┌─────────┐  ┌──────────┐  ┌────────┐  ┌──────────┐  │
│  │  MinIO  │  │PostgreSQL│  │ Qdrant │  │  Neo4j   │  │
│  │ :9000   │  │  :5432   │  │ :6333  │  │  :7687   │  │
│  └────┬────┘  └────┬─────┘  └───┬────┘  └────┬─────┘  │
│       │             │            │              │        │
│  ┌────▼─────────────▼────────────▼──────────────▼────┐  │
│  │           Prefect Orchestrator (:4200)             │  │
│  │           pipeline/flows/batch_ingest.py           │  │
│  └────────────────────────┬──────────────────────────┘  │
│                            │ SSH reverse tunnel           │
│                     localhost:9000 ←─────────────────────┤
└────────────────────────────┼────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────┐
│  JarvisLabs GPU Node (L4/L40S)                           │
│                                                          │
│  ┌─────────────────┐  ┌──────────────┐  ┌───────────┐  │
│  │  Chandra OCR    │  │ BGE-M3 Embed │  │   Qwen    │  │
│  │  :8001          │  │ :8002        │  │   :8003   │  │
│  │  chandra-ocr-2  │  │ BAAI/bge-m3  │  │ 7B-Instruct│ │
│  │  ~8GB VRAM/wkr  │  │ ~3GB VRAM    │  │ ~7GB VRAM │  │
│  └─────────────────┘  └──────────────┘  └───────────┘  │
└─────────────────────────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────┐
│  Query API (FastAPI)                                      │
│  /search (vector)  /graph/* (Neo4j)  /hybrid (fused)     │
└─────────────────────────────────────────────────────────┘

Observability: Prometheus :9090  Grafana :3000  Loki :3100  Jaeger :16686
```

---

## Data Flow

| Stage | What happens |
|-------|-------------|
| 1. Discovery | Scan `raw/` in MinIO, dedup by content hash against PostgreSQL, register new docs |
| 2. Jarvis startup | Open SSH reverse tunnel (MinIO reachable from JarvisLabs), poll `/health` on all 3 services (300s timeout) |
| 3. OCR | PDF/image -> Markdown via Chandra model; output stored in `processed/`; semaphore-bounded workers |
| 4. Chunking | Heading-aware Markdown splitting -> JSONL in `chunks/`; deterministic chunk UUIDs; 128-token overlap |
| 5. Embedding | BGE-M3: dense (1024-dim) + sparse vectors -> Qdrant upsert; batched at 64 chunks/request |
| 6. Entity extraction | Qwen2.5-7B extracts entities + relations -> Neo4j (Document->Section->Chunk + Entity graph) |
| 7. Finalize | Mark docs COMPLETE, count dead-letters, close SSH tunnel |

Failed documents retry up to `MAX_RETRIES` (default 3) before moving to a dead-letter queue in PostgreSQL.

---

## Requirements

### Infrastructure
- Docker + Docker Compose (local stack)
- JarvisLabs GPU instance: L4 or L40S, **22GB+ VRAM** recommended
- SSH access to JarvisLabs (`~/.ssh/id_ed25519` or ssh-agent)
- Python 3.11+
- HuggingFace token (`HF_TOKEN`) for first-time model downloads
- Ports 8001-8003 reachable on JarvisLabs from orchestrator machine

### Compute
| Component | VRAM | Notes |
|-----------|------|-------|
| Chandra OCR | ~8 GB/worker | `OCR_WORKERS=1` default; increase if VRAM allows |
| BGE-M3 Embed | ~3 GB | Always loaded |
| Qwen2.5-7B | ~7 GB | Pauses 1 OCR worker slot while running |
| **Peak total** | **~14 GB** | All 3 services active simultaneously |

### Models (33 GB total — download once, rsync to JarvisLabs)

| Model | Size | HF Repo |
|-------|------|---------|
| Chandra OCR | 9.9 GB | `datalab-to/chandra-ocr-2` |
| BGE-M3 | 4.3 GB | `BAAI/bge-m3` |
| Qwen2.5-7B-Instruct | 19 GB | `Qwen/Qwen2.5-7B-Instruct` |

---

## Quickstart

```bash
# 1. Clone and configure
git clone https://github.com/anshulgarg-ag/ocr.git && cd ocr
cp .env.example .env
# Edit .env: set JARVIS_HOST, passwords, SSH key path

# 2. Start local stack
docker compose up -d

# 3. Download models locally and upload to JarvisLabs (first time only)
python download_models.py --token hf_xxx
rsync -avz --progress models/ ubuntu@<JARVIS_IP>:~/models/

# 4. Deploy GPU services to JarvisLabs
bash deploy_jarvis.sh

# 5. Drop PDFs into MinIO raw/ bucket, then trigger pipeline
python -m pipeline.flows.batch_ingest

# Schedule via Prefect (daily at 2 AM)
prefect deploy --cron "0 2 * * *"
```

---

## Services & Ports

| Service | Port | Purpose | Image |
|---------|------|---------|-------|
| MinIO | 9000 / 9001 | Object storage (raw, processed, chunks) | minio/minio |
| PostgreSQL | 5432 | Pipeline state + dead-letter queue | postgres:16-alpine |
| Qdrant | 6333 / 6334 | Vector store (dense + sparse) | qdrant/qdrant |
| Neo4j | 7474 / 7687 | Knowledge graph | neo4j:5-community |
| Prefect | 4200 | Flow orchestration UI | prefecthq/prefect:3 |
| Prometheus | 9090 | Metrics collection | prom/prometheus |
| Grafana | 3000 | Metrics dashboards | grafana/grafana |
| Loki | 3100 | Log aggregation | grafana/loki |
| Jaeger | 16686 | Distributed tracing | jaegertracing/all-in-one |
| Chandra OCR | 8001 | OCR service (JarvisLabs) | FastAPI + chandra-ocr |
| BGE-M3 Embed | 8002 | Embedding service (JarvisLabs) | FastAPI + FlagEmbedding |
| Qwen Graph | 8003 | Entity extraction (JarvisLabs) | FastAPI + transformers |
| Query API | 8000 | Hybrid search API | FastAPI |

---

## Configuration

Key `.env` variables (full list in `.env.example`):

```bash
# Storage — swap s3:// for gs:// (GCS) or az:// (Azure) without code changes
STORAGE_ROOT=s3://ocr-pipeline
MINIO_ENDPOINT=http://localhost:9000

# JarvisLabs — update IP each new instance
JARVIS_HOST=<instance-ip>
JARVIS_MAX_RUNTIME_HOURS=12     # watchdog hard-stop
JARVIS_OCR_URL=http://<ip>:8001
JARVIS_EMBED_URL=http://<ip>:8002
JARVIS_GRAPH_URL=http://<ip>:8003

# Model paths on JarvisLabs (after rsync)
OCR_MODEL=/home/ubuntu/models/chandra-ocr-2
EMBED_MODEL=/home/ubuntu/models/bge-m3
GRAPH_MODEL=/home/ubuntu/models/Qwen2.5-7B-Instruct

# Pipeline tuning
OCR_WORKERS=1                   # concurrent OCR workers (VRAM-bounded)
EMBED_BATCH_SIZE=64             # chunks per embedding request
MAX_RETRIES=3                   # failed doc retry limit
ENTITY_CONFIDENCE_MIN=0.6       # min LLM confidence to store entities
CHUNK_MAX_TOKENS=1024           # max tokens per chunk
CHUNK_OVERLAP_TOKENS=128        # sliding window overlap
```

---

## Query API

```
POST /search
  {"query": str, "top_k": 10, "score_threshold": 0.3}
  Semantic vector search via Qdrant (dense + sparse hybrid)

GET  /graph/entities/{name}?depth=2
  Entity neighborhood traversal in Neo4j

POST /graph/documents-by-entity
  {"entity_name": str}
  All documents mentioning an entity, sorted by confidence

GET  /graph/document/{doc_id}/graph
  Full knowledge graph for one document (structure + entities)

GET  /graph/cooccurring-entities?entity_a=X&entity_b=Y
  Documents where both entities appear together

POST /hybrid
  {"query": str, "top_k": 10, "include_graph_context": true}
  Vector search + Neo4j entity/relation context fused per result
```

---

## Limitations

- **Single-machine orchestrator** — Prefect flow runs on one machine; no distributed workers
- **JarvisLabs disk resets** — Instance storage is ephemeral; models must be rsync'd on every new instance (33 GB transfer)
- **No persistent volume** — Attaching a JarvisLabs persistent volume would eliminate the rsync step (not yet configured)
- **Discovery loads full file list into memory** — No pagination; impractical beyond ~100k files in `raw/`
- **SSH tunnel is a single point of failure** — If the reverse tunnel drops mid-batch, the batch fails; no auto-reconnect
- **Entity extraction truncates at 8000 chars** — Long documents are cut before LLM processing; multi-chunk extraction not implemented
- **No authentication on Query API** — All endpoints are open; add a reverse proxy with JWT/API key before exposing publicly
- **Hardcoded timeouts** — OCR: 600s, entity extraction: 300s, embedding: 120s — not configurable via `.env`
- **Chunk token count is approximate** — Uses `char_count / 4`; actual token count may vary ~15%
- **vLLM disabled** — Incompatible with `torch._inductor` on current CUDA setup; Qwen2.5-7B uses `transformers` directly (slower throughput than vLLM)

---

## Observability

| Tool | URL | Credentials |
|------|-----|------------|
| Prefect | http://localhost:4200 | none |
| Grafana | http://localhost:3000 | admin / admin |
| Jaeger | http://localhost:16686 | none |
| Neo4j Browser | http://localhost:7474 | neo4j / neo4jpassword |
| MinIO Console | http://localhost:9001 | minioadmin / minioadmin |

---

## Project Structure

```
.
├── pipeline/
│   ├── flows/batch_ingest.py   # Prefect flow — 7-stage orchestration
│   └── tasks/                  # discovery, chunker, ocr_client, embed_client,
│                               # neo4j_writer, state, storage_ops, jarvis_ops
├── jarvis_services/            # FastAPI services deployed to JarvisLabs GPU node
│   ├── chandra_server.py       # OCR service :8001
│   ├── embed_server.py         # Embedding service :8002
│   ├── graph_server.py         # Entity extraction service :8003
│   └── requirements.txt        # GPU service dependencies
├── query_api/                  # FastAPI hybrid search API
├── config/settings.py          # Pydantic settings (all env vars)
├── infra/docker-compose.yml    # Local stack (MinIO, Postgres, Qdrant, Neo4j, observability)
├── migrations/                 # Alembic DB migrations
├── observability/              # Metrics, tracing, alert helpers
├── tests/                      # Unit + integration tests
├── download_models.py          # One-time model download script
├── deploy_jarvis.sh            # JarvisLabs deploy script
├── .env.example                # All config vars with defaults
└── remember.md                 # Operational notes and gotchas
```
