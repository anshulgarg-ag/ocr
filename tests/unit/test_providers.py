"""Unit tests for GPU provider implementations."""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from pipeline.providers.jarvis import JarvisLabsProvider
from pipeline.providers.self_hosted import SelfHostedProvider


class TestJarvisLabsProvider:
    """Tests for JarvisLabsProvider."""

    def test_init_reads_env_vars(self, monkeypatch):
        """Verify __init__ reads host/user from environment."""
        monkeypatch.setenv("JARVIS_HOST", "192.168.1.100")
        monkeypatch.setenv("JARVIS_USER", "ubuntu")
        monkeypatch.setenv("JARVIS_OCR_URL", "http://192.168.1.100:8001")

        provider = JarvisLabsProvider()
        assert provider.host == "192.168.1.100"
        assert provider.user == "ubuntu"

    def test_init_ssh_key_optional(self, monkeypatch):
        """Verify SSH key path is optional."""
        monkeypatch.delenv("JARVIS_SSH_KEY_PATH", raising=False)

        provider = JarvisLabsProvider()
        assert provider.ssh_key_path is None or provider.ssh_key_path == ""

    @pytest.mark.asyncio
    async def test_start_calls_open_tunnel_and_returns_endpoints(self, monkeypatch):
        """Verify start() opens tunnel and returns ServiceEndpoints."""
        monkeypatch.setenv("JARVIS_HOST", "192.168.1.100")
        monkeypatch.setenv("JARVIS_OCR_URL", "http://192.168.1.100:8001")

        mock_tunnel = MagicMock()
        monkeypatch.setattr(
            "pipeline.providers.jarvis.JarvisLabsProvider._open_tunnel",
            lambda self: mock_tunnel,
        )

        provider = JarvisLabsProvider()
        endpoints = await provider.start()

        assert endpoints is not None
        assert endpoints.ocr_url
        assert endpoints.embed_url
        assert endpoints.graph_url
        assert endpoints.storage_url == "http://localhost:9000"

    def test_open_tunnel_includes_ssh_key_when_set(self, monkeypatch):
        """Verify _open_tunnel includes -i flag when SSH key is configured."""
        monkeypatch.setenv("JARVIS_HOST", "192.168.1.100")
        monkeypatch.setenv("JARVIS_SSH_KEY_PATH", "/home/user/.ssh/id_rsa")

        mock_popen = MagicMock()
        mock_popen.poll.return_value = None

        captured_cmd = []

        def mock_popen_init(*args, **kwargs):
            captured_cmd.append(args[0])
            return mock_popen

        monkeypatch.setattr("pipeline.providers.jarvis.subprocess.Popen", mock_popen_init)
        monkeypatch.setattr("pipeline.providers.jarvis.time.sleep", MagicMock())

        provider = JarvisLabsProvider()
        provider._open_tunnel()

        cmd = captured_cmd[0]
        assert "-i" in cmd
        assert "/home/user/.ssh/id_rsa" in cmd

    def test_open_tunnel_omits_ssh_key_when_unset(self, monkeypatch):
        """Verify _open_tunnel excludes -i flag when SSH key not set."""
        monkeypatch.setenv("JARVIS_HOST", "192.168.1.100")
        monkeypatch.delenv("JARVIS_SSH_KEY_PATH", raising=False)

        mock_popen = MagicMock()
        mock_popen.poll.return_value = None

        captured_cmd = []

        def mock_popen_init(*args, **kwargs):
            captured_cmd.append(args[0])
            return mock_popen

        monkeypatch.setattr("pipeline.providers.jarvis.subprocess.Popen", mock_popen_init)
        monkeypatch.setattr("pipeline.providers.jarvis.time.sleep", MagicMock())

        provider = JarvisLabsProvider()
        provider._open_tunnel()

        cmd = captured_cmd[0]
        assert "-i" not in cmd

    def test_open_tunnel_raises_if_process_dies(self, monkeypatch):
        """Verify _open_tunnel raises RuntimeError if process exits."""
        monkeypatch.setenv("JARVIS_HOST", "192.168.1.100")

        mock_popen = MagicMock()
        mock_popen.poll.return_value = 1

        monkeypatch.setattr("pipeline.providers.jarvis.subprocess.Popen", lambda cmd: mock_popen)
        monkeypatch.setattr("pipeline.providers.jarvis.time.sleep", MagicMock())

        provider = JarvisLabsProvider()
        with pytest.raises(RuntimeError, match="SSH reverse tunnel failed"):
            provider._open_tunnel()

    @pytest.mark.asyncio
    async def test_wait_for_services_success(self, monkeypatch):
        """Verify wait_for_services succeeds with healthy services."""
        monkeypatch.setenv("JARVIS_HOST", "192.168.1.100")
        monkeypatch.setenv("JARVIS_OCR_URL", "http://192.168.1.100:8001")

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        monkeypatch.setattr("pipeline.providers.jarvis.httpx.AsyncClient", lambda **kw: mock_client)
        monkeypatch.setattr("pipeline.providers.jarvis.asyncio.sleep", AsyncMock())

        provider = JarvisLabsProvider()
        await provider.wait_for_services(timeout=10)

    @pytest.mark.asyncio
    async def test_wait_for_services_timeout_raises(self, monkeypatch):
        """Verify wait_for_services raises TimeoutError after timeout."""
        monkeypatch.setenv("JARVIS_HOST", "192.168.1.100")
        monkeypatch.setenv("JARVIS_OCR_URL", "http://192.168.1.100:8001")

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("Connection refused"))

        monkeypatch.setattr("pipeline.providers.jarvis.httpx.AsyncClient", lambda **kw: mock_client)
        monkeypatch.setattr("pipeline.providers.jarvis.asyncio.sleep", AsyncMock())

        time_values = [0.0, 1000.0]
        time_index = [0]

        def mock_monotonic():
            val = time_values[min(time_index[0], len(time_values) - 1)]
            time_index[0] += 1
            return val

        monkeypatch.setattr("pipeline.providers.jarvis.asyncio.get_event_loop", lambda: MagicMock(time=mock_monotonic))

        provider = JarvisLabsProvider()
        with pytest.raises(TimeoutError):
            await provider.wait_for_services(timeout=1)

    @pytest.mark.asyncio
    async def test_stop_terminates_tunnel(self, monkeypatch):
        """Verify stop() terminates the tunnel process."""
        monkeypatch.setenv("JARVIS_HOST", "192.168.1.100")

        provider = JarvisLabsProvider()

        mock_tunnel = MagicMock()
        mock_tunnel.poll.return_value = None
        provider._tunnel_proc = mock_tunnel

        await provider.stop()

        mock_tunnel.terminate.assert_called_once()
        assert provider._tunnel_proc is None


class TestSelfHostedProvider:
    """Tests for SelfHostedProvider."""

    def test_init_reads_env_vars(self, monkeypatch):
        """Verify __init__ reads GPU URLs from environment."""
        monkeypatch.setenv("GPU_OCR_URL", "http://localhost:8001")
        monkeypatch.setenv("GPU_EMBED_URL", "http://localhost:8002")
        monkeypatch.setenv("GPU_GRAPH_URL", "http://localhost:8003")

        provider = SelfHostedProvider()
        assert provider.ocr_url == "http://localhost:8001"
        assert provider.embed_url == "http://localhost:8002"
        assert provider.graph_url == "http://localhost:8003"

    @pytest.mark.asyncio
    async def test_start_returns_endpoints(self, monkeypatch):
        """Verify start() returns ServiceEndpoints without I/O."""
        monkeypatch.setenv("GPU_OCR_URL", "http://localhost:8001")
        monkeypatch.setenv("GPU_EMBED_URL", "http://localhost:8002")
        monkeypatch.setenv("GPU_GRAPH_URL", "http://localhost:8003")
        monkeypatch.setenv("MINIO_ENDPOINT", "http://localhost:9000")

        provider = SelfHostedProvider()
        endpoints = await provider.start()

        assert endpoints.ocr_url == "http://localhost:8001"
        assert endpoints.embed_url == "http://localhost:8002"
        assert endpoints.graph_url == "http://localhost:8003"
        assert endpoints.storage_url == "http://localhost:9000"

    @pytest.mark.asyncio
    async def test_wait_for_services_success(self, monkeypatch):
        """Verify wait_for_services succeeds with healthy services."""
        monkeypatch.setenv("GPU_OCR_URL", "http://localhost:8001")

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        monkeypatch.setattr("pipeline.providers.self_hosted.httpx.AsyncClient", lambda **kw: mock_client)
        monkeypatch.setattr("pipeline.providers.self_hosted.asyncio.sleep", AsyncMock())

        provider = SelfHostedProvider()
        await provider.wait_for_services(timeout=10)

    @pytest.mark.asyncio
    async def test_stop_is_noop(self, monkeypatch):
        """Verify stop() is a no-op for self-hosted provider."""
        monkeypatch.setenv("GPU_OCR_URL", "http://localhost:8001")

        provider = SelfHostedProvider()
        await provider.stop()
