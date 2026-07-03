import os
from .base import GPUProvider
from .self_hosted import SelfHostedProvider
from .jarvis import JarvisLabsProvider


def create_gpu_provider(provider_type: str | None = None) -> GPUProvider:
    t = provider_type or os.environ.get("GPU_PROVIDER_TYPE", "self_hosted")
    if t == "self_hosted":
        return SelfHostedProvider()
    if t == "jarvis":
        return JarvisLabsProvider()
    raise ValueError(f"Unknown GPU_PROVIDER_TYPE: {t!r}. Options: self_hosted, jarvis")
