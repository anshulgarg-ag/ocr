import asyncio
import os
import subprocess
import time
import httpx
from .base import GPUProvider, ServiceEndpoints


class JarvisLabsProvider(GPUProvider):
    def __init__(self):
        self.host = os.environ.get("JARVIS_HOST", "")
        self.user = os.environ.get("JARVIS_USER", "ubuntu")
        self.ssh_key_path = os.environ.get("JARVIS_SSH_KEY_PATH", "")
        self.ocr_url = os.environ.get("JARVIS_OCR_URL", f"http://{self.host}:8001")
        self.embed_url = os.environ.get("JARVIS_EMBED_URL", f"http://{self.host}:8002")
        self.graph_url = os.environ.get("JARVIS_GRAPH_URL", f"http://{self.host}:8003")
        self._tunnel_proc: subprocess.Popen | None = None

    async def start(self) -> ServiceEndpoints:
        self._open_tunnel()
        return ServiceEndpoints(
            ocr_url=self.ocr_url,
            embed_url=self.embed_url,
            graph_url=self.graph_url,
            storage_url="http://localhost:9000",  # via reverse tunnel
        )

    def _open_tunnel(self) -> None:
        cmd = [
            "ssh",
            "-o", "StrictHostKeyChecking=no",
            "-o", "ExitOnForwardFailure=yes",
            "-o", "ServerAliveInterval=30",
            "-o", "ServerAliveCountMax=3",
            "-fN",
            "-R", "9000:localhost:9000",
        ]
        if self.ssh_key_path:
            cmd += ["-i", self.ssh_key_path]
        cmd.append(f"{self.user}@{self.host}")
        self._tunnel_proc = subprocess.Popen(cmd)
        time.sleep(3)
        if self._tunnel_proc.poll() is not None:
            raise RuntimeError("SSH reverse tunnel failed to open")

    async def wait_for_services(self, timeout: int = 300) -> None:
        urls = {
            "ocr": self.ocr_url + "/health",
            "embed": self.embed_url + "/health",
            "graph": self.graph_url + "/health",
        }
        deadline = asyncio.get_event_loop().time() + timeout
        pending = set(urls.keys())
        async with httpx.AsyncClient(timeout=5) as client:
            while pending and asyncio.get_event_loop().time() < deadline:
                for name in list(pending):
                    try:
                        r = await client.get(urls[name])
                        if r.status_code == 200:
                            pending.discard(name)
                    except Exception:
                        pass
                if pending:
                    await asyncio.sleep(10)
        if pending:
            raise TimeoutError(f"Services not ready after {timeout}s: {pending}")

    async def stop(self) -> None:
        if self._tunnel_proc and self._tunnel_proc.poll() is None:
            self._tunnel_proc.terminate()
            self._tunnel_proc = None
