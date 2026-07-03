import asyncio
import os
import httpx
from .base import GPUProvider, ServiceEndpoints


class SelfHostedProvider(GPUProvider):
    """Services already running locally or on a reachable host."""

    def __init__(self):
        self.ocr_url = os.environ.get("GPU_OCR_URL", "http://localhost:8001")
        self.embed_url = os.environ.get("GPU_EMBED_URL", "http://localhost:8002")
        self.graph_url = os.environ.get("GPU_GRAPH_URL", "http://localhost:8003")
        self.minio_url = os.environ.get("MINIO_ENDPOINT", "http://localhost:9000")

    async def start(self) -> ServiceEndpoints:
        return ServiceEndpoints(
            ocr_url=self.ocr_url,
            embed_url=self.embed_url,
            graph_url=self.graph_url,
            storage_url=self.minio_url,
        )

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
        pass  # nothing to tear down
