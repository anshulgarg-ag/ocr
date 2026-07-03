from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ServiceEndpoints:
    ocr_url: str
    embed_url: str
    graph_url: str
    storage_url: str  # as seen from GPU (reverse tunnel vs direct)


class GPUProvider(ABC):
    @abstractmethod
    async def start(self) -> ServiceEndpoints:
        """Start GPU services and return endpoints."""

    @abstractmethod
    async def wait_for_services(self, timeout: int = 300) -> None:
        """Poll health endpoints until all services ready."""

    @abstractmethod
    async def stop(self) -> None:
        """Cleanup: close tunnels, teardown, etc."""
