import subprocess
import threading
import time

from prometheus_client import Counter, Gauge, Histogram, start_http_server

from config.settings import settings

# ── Counters ──────────────────────────────────────────────────────────────────
docs_processed = Counter("docs_processed_total", "Documents completed all stages", ["batch_id"])
docs_failed = Counter("docs_failed_total", "Documents that hit dead-letter queue", ["stage"])

# ── Gauges ────────────────────────────────────────────────────────────────────
docs_in_flight = Gauge("docs_in_flight", "Documents currently being processed")
vram_used_gb = Gauge("vram_used_gb", "GPU VRAM used in GB (reported by JarvisLabs services)")
ocr_pages_per_second = Gauge("ocr_pages_per_second", "OCR throughput", ["worker_id"])

# ── Histograms ────────────────────────────────────────────────────────────────
ocr_duration = Histogram(
    "ocr_duration_seconds", "Time to OCR one document", buckets=[5, 10, 30, 60, 120, 300]
)
embed_batch_duration = Histogram(
    "embed_batch_duration_ms",
    "BGE-M3 embedding batch latency (ms)",
    buckets=[50, 100, 250, 500, 1000, 2000],
)
neo4j_write_latency = Histogram(
    "neo4j_write_latency_ms",
    "Neo4j MERGE write latency (ms)",
    buckets=[10, 50, 100, 500, 1000],
)
storage_upload_duration = Histogram(
    "storage_upload_duration_seconds",
    "Storage upload latency",
    buckets=[1, 5, 10, 30, 60],
)


def start_metrics_server() -> None:
    start_http_server(settings.prometheus_port)


def _poll_nvidia_smi(interval: int = 30) -> None:
    """Background thread: poll nvidia-smi on localhost if available."""
    while True:
        try:
            out = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                timeout=5,
            )
            used_mib = int(out.decode().strip().split("\n")[0])
            vram_used_gb.set(round(used_mib / 1024, 2))
        except Exception:
            pass
        time.sleep(interval)


def start_vram_poller() -> None:
    t = threading.Thread(target=_poll_nvidia_smi, daemon=True)
    t.start()
