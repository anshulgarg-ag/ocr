#!/bin/bash
# Run this from YOUR terminal (where your JarvisLabs SSH key works)
# Usage: bash deploy_jarvis.sh
set -e

JARVIS_HOST="217.18.55.79"
JARVIS_USER="ubuntu"
SSH_OPTS="-o StrictHostKeyChecking=no"

# JarvisLabs is remote — MinIO runs locally.
# We open a reverse SSH tunnel so JarvisLabs sees MinIO at localhost:9000.
# No firewall changes needed on your router.

echo "=== Deploying OCR services to JarvisLabs ($JARVIS_HOST) ==="

# ── 1. Open reverse tunnel (background): JarvisLabs:9000 → your MinIO:9000 ───
echo "Opening reverse SSH tunnel (MinIO ← localhost:9000 on JarvisLabs)..."
ssh $SSH_OPTS -fN \
    -R 9000:localhost:9000 \
    ${JARVIS_USER}@${JARVIS_HOST}
TUNNEL_PID=$(pgrep -f "ssh.*-R 9000:localhost:9000.*${JARVIS_HOST}" | head -1)
echo "✓ Tunnel open (PID: $TUNNEL_PID)"

# ── 2. Upload service files ────────────────────────────────────────────────────
echo "Uploading service files..."
ssh $SSH_OPTS ${JARVIS_USER}@${JARVIS_HOST} "mkdir -p ~/ocr_services"
scp $SSH_OPTS \
    jarvis_services/chandra_server.py \
    jarvis_services/embed_server.py \
    jarvis_services/graph_server.py \
    jarvis_services/requirements.txt \
    ${JARVIS_USER}@${JARVIS_HOST}:~/ocr_services/
echo "✓ Files uploaded"

# ── 3. Write .env on remote (MinIO at localhost:9000 via tunnel) ──────────────
echo "Writing environment config..."
ssh $SSH_OPTS ${JARVIS_USER}@${JARVIS_HOST} "cat > ~/ocr_services/.env" <<EOF
STORAGE_ROOT=s3://ocr-pipeline
MINIO_ENDPOINT=http://localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
OCR_WORKERS=3
ENTITY_CONFIDENCE_MIN=0.6
EOF
echo "✓ Config written (MinIO via reverse tunnel)"

# ── 4. Verify tunnel works before starting model downloads ───────────────────
echo "Verifying MinIO is reachable from JarvisLabs..."
ssh $SSH_OPTS ${JARVIS_USER}@${JARVIS_HOST} \
    "curl -sf http://localhost:9000/minio/health/live && echo 'MinIO reachable ✓' || echo 'MinIO NOT reachable — check tunnel'"

# ── 5. Upload and run startup script ──────────────────────────────────────────
echo "Uploading startup script..."
scp $SSH_OPTS jarvis_services/startup.sh ${JARVIS_USER}@${JARVIS_HOST}:~/ocr_services/

echo ""
echo "Running startup — installs Python deps and downloads model weights."
echo "This takes 20-40 min. You will see live progress."
echo ""
ssh $SSH_OPTS ${JARVIS_USER}@${JARVIS_HOST} "
    set -e
    cd ~/ocr_services
    set -a; source .env; set +a
    export SERVICE_DIR=~/ocr_services
    bash startup.sh
"

echo ""
echo "=== Deployment complete ==="
echo "Services running on $JARVIS_HOST:"
echo "  OCR:    http://${JARVIS_HOST}:8001/health"
echo "  Embed:  http://${JARVIS_HOST}:8002/health"
echo "  Graph:  http://${JARVIS_HOST}:8003/health"
echo ""
echo "Reverse tunnel PID: $TUNNEL_PID"
echo "To close tunnel later: kill $TUNNEL_PID"
