import pytest
from pipeline.providers.factory import create_gpu_provider
from pipeline.providers.self_hosted import SelfHostedProvider
from pipeline.providers.jarvis import JarvisLabsProvider


def test_default_is_self_hosted(monkeypatch):
    monkeypatch.delenv("GPU_PROVIDER_TYPE", raising=False)
    p = create_gpu_provider()
    assert isinstance(p, SelfHostedProvider)


def test_explicit_self_hosted(monkeypatch):
    monkeypatch.setenv("GPU_PROVIDER_TYPE", "self_hosted")
    p = create_gpu_provider()
    assert isinstance(p, SelfHostedProvider)


def test_explicit_jarvis(monkeypatch):
    monkeypatch.setenv("GPU_PROVIDER_TYPE", "jarvis")
    p = create_gpu_provider()
    assert isinstance(p, JarvisLabsProvider)


def test_unknown_provider_raises():
    with pytest.raises(ValueError, match="Unknown GPU_PROVIDER_TYPE"):
        create_gpu_provider("unknown_cloud")


def test_override_via_argument(monkeypatch):
    monkeypatch.setenv("GPU_PROVIDER_TYPE", "jarvis")
    p = create_gpu_provider("self_hosted")  # arg overrides env
    assert isinstance(p, SelfHostedProvider)
