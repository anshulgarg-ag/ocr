"""
JarvisLabs instance lifecycle management.

Network topology:
  Your machine (MinIO on :9000) ←── reverse SSH tunnel ──→ JarvisLabs (sees MinIO at localhost:9000)

The reverse tunnel is opened when the batch starts and torn down in the finally block.
JarvisLabs services use MINIO_ENDPOINT=http://localhost:9000 — no public exposure needed.
"""
from __future__ import annotations

import asyncio
import subprocess
import time

import httpx
import stamina

from config.logging import get_logger
from config.settings import settings

log = get_logger(__name__)

JARVIS_HOST = "217.18.55.79"
JARVIS_USER = "ubuntu"
SSH_BASE = ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ExitOnForwardFailure=yes"]

# Holds the reverse tunnel subprocess reference during a batch
_tunnel_proc: subprocess.Popen | None = None


def open_reverse_tunnel() -> subprocess.Popen:
    """
    Open a background SSH reverse tunnel:
      JarvisLabs localhost:9000 → your machine localhost:9000 (MinIO)

    Returns the subprocess so the caller can kill it in a finally block.
    """
    global _tunnel_proc
    cmd = [
        *SSH_BASE,
        "-fN",                           # background, no command
        "-o", "ServerAliveInterval=30",  # keep-alive so tunnel doesn't drop
        "-o", "ServerAliveCountMax=3",
        "-R", "9000:localhost:9000",      # remote:9000 → local:9000
        f"{JARVIS_USER}@{JARVIS_HOST}",
    ]
    if settings.jarvis_ssh_key_path:
        cmd = cmd[:1] + ["-i", settings.jarvis_ssh_key_path] + cmd[1:]

    _tunnel_proc = subprocess.Popen(cmd)
    time.sleep(3)  # give SSH time to establish
    if _tunnel_proc.poll() is not None:
        raise RuntimeError("SSH reverse tunnel failed to open — check your SSH key and host connectivity")
    log.info("reverse_tunnel_open", local_port=9000, remote_port=9000)
    return _tunnel_proc


def close_reverse_tunnel() -> None:
    global _tunnel_proc
    if _tunnel_proc and _tunnel_proc.poll() is None:
        _tunnel_proc.terminate()
        _tunnel_proc = None
        log.info("reverse_tunnel_closed")


async def wait_for_services(timeout: int = 300) -> None:
    """Poll JarvisLabs service health endpoints until all are up."""
    urls = {
        "ocr":   f"http://{JARVIS_HOST}:8001/health",
        "embed": f"http://{JARVIS_HOST}:8002/health",
        "graph": f"http://{JARVIS_HOST}:8003/health",
    }
    deadline = time.monotonic() + timeout
    async with httpx.AsyncClient(timeout=5) as client:
        pending = dict(urls)
        while pending and time.monotonic() < deadline:
            for name, url in list(pending.items()):
                try:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        log.info("jarvis_service_ready", service=name)
                        del pending[name]
                except Exception:
                    pass
            if pending:
                await asyncio.sleep(10)
    if pending:
        raise TimeoutError(f"JarvisLabs services not ready after {timeout}s: {list(pending)}")


async def start_instance() -> None:
    """Open reverse tunnel and verify all GPU services are up."""
    open_reverse_tunnel()
    await wait_for_services(timeout=300)


async def stop_instance() -> None:
    """Close reverse tunnel. Called in finally block — always runs."""
    close_reverse_tunnel()
    log.info("jarvis_session_ended")


async def watchdog(start_time: float) -> None:
    """Async task that hard-stops the session if MAX_RUNTIME_HOURS is exceeded."""
    max_seconds = settings.jarvis_max_runtime_hours * 3600
    await asyncio.sleep(max_seconds)
    elapsed_h = (time.monotonic() - start_time) / 3600
    log.error("jarvis_watchdog_triggered", elapsed_hours=round(elapsed_h, 2))
    close_reverse_tunnel()
