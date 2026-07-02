#!/bin/bash
# JarvisLabs L40S startup script
# Run once after spinning up a new instance (or on each start if not persistent)
set -e

echo "=== OCR Pipeline: JarvisLabs Startup ==="

# ── 1. Install Python deps ────────────────────────────────────────────────────
pip install --quiet --upgrade pip
pip install --quiet \
    "chandra-ocr>=0.1" \
    "FlagEmbedding>=1.2" \
    "vllm>=0.5" \
    "fastapi>=0.111" \
    "uvicorn[standard]>=0.30" \
    "s3fs>=2024.0" \
    "prometheus-client>=0.20" \
    "pydantic>=2.0"

echo "✓ Python deps installed"

# ── 2. Copy service files (already uploaded by orchestrator via SCP) ──────────
SERVICE_DIR="${HOME}/ocr_services"
mkdir -p "${SERVICE_DIR}"

# ── 3. Set env vars (passed in from orchestrator via SSH env or .env file) ────
export STORAGE_ROOT="${STORAGE_ROOT:-s3://ocr-pipeline}"
export MINIO_ENDPOINT="${MINIO_ENDPOINT:-http://REPLACE_ME:9000}"
export MINIO_ACCESS_KEY="${MINIO_ACCESS_KEY:-minioadmin}"
export MINIO_SECRET_KEY="${MINIO_SECRET_KEY:-minioadmin}"
export OCR_WORKERS="${OCR_WORKERS:-3}"
export ENTITY_CONFIDENCE_MIN="${ENTITY_CONFIDENCE_MIN:-0.6}"

# ── 4. Pre-download model weights (HuggingFace Hub) ──────────────────────────
python -c "
from huggingface_hub import snapshot_download
print('Downloading Chandra OCR weights...')
snapshot_download('datalab-to/chandra-ocr-2', local_dir='/models/chandra')
print('Downloading BGE-M3 weights...')
snapshot_download('BAAI/bge-m3', local_dir='/models/bge-m3')
print('Downloading Qwen2.5-7B weights...')
snapshot_download('Qwen/Qwen2.5-7B-Instruct', local_dir='/models/qwen25-7b')
print('All weights downloaded.')
"
echo "✓ Model weights ready"

# ── 5. Start all three services in background ─────────────────────────────────
echo "Starting OCR service (port 8001)..."
nohup python "${SERVICE_DIR}/chandra_server.py" > /var/log/ocr_service.log 2>&1 &
echo $! > /var/run/ocr_service.pid

echo "Starting embedding service (port 8002)..."
nohup python "${SERVICE_DIR}/embed_server.py" > /var/log/embed_service.log 2>&1 &
echo $! > /var/run/embed_service.pid

echo "Starting graph extraction service (port 8003)..."
nohup python "${SERVICE_DIR}/graph_server.py" > /var/log/graph_service.log 2>&1 &
echo $! > /var/run/graph_service.pid

echo "Waiting for services to be ready..."
sleep 30

for PORT in 8001 8002 8003; do
    until curl -sf "http://localhost:${PORT}/health" > /dev/null; do
        echo "  Waiting for port ${PORT}..."
        sleep 5
    done
    echo "  ✓ Service on port ${PORT} ready"
done

echo "=== All services ready ==="
