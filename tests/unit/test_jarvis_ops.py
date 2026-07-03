import itertools

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pipeline.tasks.jarvis_ops import (
    open_reverse_tunnel,
    close_reverse_tunnel,
    wait_for_services,
    start_instance,
    stop_instance,
    watchdog,
)


def test_open_reverse_tunnel_success(monkeypatch):
    mock_popen = MagicMock()
    mock_popen.poll.return_value = None

    monkeypatch.setattr("pipeline.tasks.jarvis_ops.subprocess.Popen", lambda *a, **kw: mock_popen)
    monkeypatch.setattr("pipeline.tasks.jarvis_ops.time.sleep", MagicMock())

    result = open_reverse_tunnel()

    assert result == mock_popen


def test_open_reverse_tunnel_inserts_ssh_key_flag_when_configured(monkeypatch):
    mock_popen = MagicMock()
    mock_popen.poll.return_value = None

    captured_cmd = []

    def mock_popen_init(*args, **kwargs):
        captured_cmd.append(args[0])
        return mock_popen

    monkeypatch.setattr("pipeline.tasks.jarvis_ops.subprocess.Popen", mock_popen_init)
    monkeypatch.setattr("pipeline.tasks.jarvis_ops.time.sleep", MagicMock())
    monkeypatch.setattr("pipeline.tasks.jarvis_ops.settings.jarvis_ssh_key_path", "/home/user/.ssh/id_rsa")

    open_reverse_tunnel()

    assert "-i" in captured_cmd[0]
    assert "/home/user/.ssh/id_rsa" in captured_cmd[0]


def test_open_reverse_tunnel_raises_if_process_dies(monkeypatch):
    mock_popen = MagicMock()
    mock_popen.poll.return_value = 1

    monkeypatch.setattr("pipeline.tasks.jarvis_ops.subprocess.Popen", lambda *a, **kw: mock_popen)
    monkeypatch.setattr("pipeline.tasks.jarvis_ops.time.sleep", MagicMock())

    with pytest.raises(RuntimeError, match="SSH reverse tunnel failed"):
        open_reverse_tunnel()


def test_close_reverse_tunnel_terminates_running_process(monkeypatch):
    mock_popen = MagicMock()
    mock_popen.poll.return_value = None
    monkeypatch.setattr("pipeline.tasks.jarvis_ops._tunnel_proc", mock_popen)

    import pipeline.tasks.jarvis_ops
    pipeline.tasks.jarvis_ops._tunnel_proc = mock_popen

    close_reverse_tunnel()

    mock_popen.terminate.assert_called_once()


def test_close_reverse_tunnel_noop_when_already_exited_leaves_global(monkeypatch):
    mock_popen = MagicMock()
    mock_popen.poll.return_value = 0

    import pipeline.tasks.jarvis_ops
    pipeline.tasks.jarvis_ops._tunnel_proc = mock_popen

    close_reverse_tunnel()

    mock_popen.terminate.assert_not_called()


async def test_wait_for_services_all_ready(monkeypatch):
    async def mock_get(*args, **kwargs):
        response = MagicMock()
        response.status_code = 200
        return response

    mock_client = AsyncMock()
    mock_client.get = mock_get
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    monkeypatch.setattr("pipeline.tasks.jarvis_ops.httpx.AsyncClient", lambda *a, **kw: mock_client)
    monkeypatch.setattr("pipeline.tasks.jarvis_ops.time.monotonic", MagicMock(return_value=0.0))

    await wait_for_services(timeout=10)


async def test_wait_for_services_swallows_transient_errors_and_retries(monkeypatch):
    import httpx
    call_count = [0]

    async def mock_get(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] < 2:
            raise httpx.ConnectError("Connection refused")
        response = MagicMock()
        response.status_code = 200
        return response

    mock_client = AsyncMock()
    mock_client.get = mock_get
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    monkeypatch.setattr("pipeline.tasks.jarvis_ops.httpx.AsyncClient", lambda *a, **kw: mock_client)
    monkeypatch.setattr("pipeline.tasks.jarvis_ops.asyncio.sleep", AsyncMock())

    time_values = [0.0, 0.0, 0.0, 5.0, 10.0, 15.0]
    time_index = [0]

    def mock_monotonic():
        val = time_values[min(time_index[0], len(time_values) - 1)]
        time_index[0] += 1
        return val

    monkeypatch.setattr("pipeline.tasks.jarvis_ops.time.monotonic", mock_monotonic)

    await wait_for_services(timeout=300)


async def test_wait_for_services_timeout_raises(monkeypatch):
    async def mock_get(*args, **kwargs):
        raise Exception("Network error")

    mock_client = AsyncMock()
    mock_client.get = mock_get
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    monkeypatch.setattr("pipeline.tasks.jarvis_ops.httpx.AsyncClient", lambda *a, **kw: mock_client)
    monkeypatch.setattr("pipeline.tasks.jarvis_ops.asyncio.sleep", AsyncMock())
    monotonic_values = itertools.chain([0.0, 1000.0], itertools.repeat(1000.0))
    monkeypatch.setattr(
        "pipeline.tasks.jarvis_ops.time.monotonic",
        MagicMock(side_effect=lambda: next(monotonic_values)),
    )

    with pytest.raises(TimeoutError):
        await wait_for_services(timeout=10)


async def test_start_instance_calls_tunnel_then_wait(monkeypatch):
    tunnel_called = [False]
    wait_called = [False]

    async def mock_wait(*args, **kwargs):
        wait_called[0] = True

    def mock_open_tunnel():
        tunnel_called[0] = True
        return MagicMock()

    monkeypatch.setattr("pipeline.tasks.jarvis_ops.open_reverse_tunnel", mock_open_tunnel)
    monkeypatch.setattr("pipeline.tasks.jarvis_ops.wait_for_services", mock_wait)

    await start_instance()

    assert tunnel_called[0]
    assert wait_called[0]


async def test_stop_instance_calls_close_and_logs(monkeypatch):
    close_called = [False]

    def mock_close():
        close_called[0] = True

    monkeypatch.setattr("pipeline.tasks.jarvis_ops.close_reverse_tunnel", mock_close)

    await stop_instance()

    assert close_called[0]


async def test_watchdog_triggers_after_sleep_and_closes_tunnel(monkeypatch):
    close_called = [False]

    def mock_close():
        close_called[0] = True

    monkeypatch.setattr("pipeline.tasks.jarvis_ops.asyncio.sleep", AsyncMock())
    monkeypatch.setattr("pipeline.tasks.jarvis_ops.close_reverse_tunnel", mock_close)
    monkeypatch.setattr("pipeline.tasks.jarvis_ops.time.monotonic", MagicMock(return_value=100.0))
    monkeypatch.setattr("pipeline.tasks.jarvis_ops.settings.jarvis_max_runtime_hours", 0.001)

    await watchdog(50.0)

    assert close_called[0]
