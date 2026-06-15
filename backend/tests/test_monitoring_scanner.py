"""
Tests for MonitoringScanner.

Run from the backend/ directory:
    pytest tests/test_monitoring_scanner.py -v

Requirements (in addition to requirements.txt):
    pip install pytest pytest-asyncio
"""
import asyncio
import sys
import os

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Allow importing from the backend package root when running from backend/
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import httpx  # noqa: E402 — after sys.path tweak
from monitoring_scanner import MonitoringScanner  # noqa: E402

FAKE_TOKEN = "dop_v1_test_token"

# A realistic DigitalOcean metrics API response entry
METRIC_ENTRY = {
    "metric": {"host": "123456", "interface": "public", "direction": "inbound"},
    "values": [[1700000000, "0.42"]],
}


def _resp(status_code: int, result_entries: list, data_value=None) -> MagicMock:
    """Build a mock httpx.Response."""
    r = MagicMock()
    r.status_code = status_code
    if data_value is None:
        r.json.return_value = {
            "status": "success",
            "data": {"resultType": "matrix", "result": result_entries},
        }
    else:
        r.json.return_value = {"status": "success", "data": data_value}
    return r


# ── get_monitoring_status ──────────────────────────────────────────────────────

class TestGetMonitoringStatus:

    @pytest.mark.asyncio
    async def test_enabled_when_metrics_present(self):
        client = AsyncMock()
        client.get.return_value = _resp(200, [METRIC_ENTRY])
        scanner = MonitoringScanner(FAKE_TOKEN)
        result = await scanner.get_monitoring_status("123456", client, asyncio.Semaphore(1))
        assert result == "enabled"

    @pytest.mark.asyncio
    async def test_missing_when_result_empty(self):
        client = AsyncMock()
        client.get.return_value = _resp(200, [])
        scanner = MonitoringScanner(FAKE_TOKEN)
        result = await scanner.get_monitoring_status("999", client, asyncio.Semaphore(1))
        assert result == "missing"

    @pytest.mark.asyncio
    async def test_auth_error_raises_value_error(self):
        client = AsyncMock()
        client.get.return_value = _resp(401, [])
        scanner = MonitoringScanner(FAKE_TOKEN)
        with pytest.raises(ValueError, match="Invalid DigitalOcean API token"):
            await scanner.get_monitoring_status("123", client, asyncio.Semaphore(1))

    @pytest.mark.asyncio
    async def test_rate_limit_returns_unknown(self):
        """HTTP 429 must return 'unknown', not 'missing' — the agent may be installed."""
        client = AsyncMock()
        client.get.return_value = _resp(429, [])
        scanner = MonitoringScanner(FAKE_TOKEN)
        result = await scanner.get_monitoring_status("123", client, asyncio.Semaphore(1))
        assert result == "unknown"

    @pytest.mark.asyncio
    async def test_server_error_returns_unknown(self):
        """Any non-200/401/429 status must return 'unknown'."""
        client = AsyncMock()
        client.get.return_value = _resp(500, [])
        scanner = MonitoringScanner(FAKE_TOKEN)
        result = await scanner.get_monitoring_status("123", client, asyncio.Semaphore(1))
        assert result == "unknown"

    @pytest.mark.asyncio
    async def test_service_unavailable_returns_unknown(self):
        client = AsyncMock()
        client.get.return_value = _resp(503, [])
        scanner = MonitoringScanner(FAKE_TOKEN)
        result = await scanner.get_monitoring_status("123", client, asyncio.Semaphore(1))
        assert result == "unknown"

    @pytest.mark.asyncio
    async def test_timeout_returns_unknown(self):
        """Timeout must return 'unknown', not 'missing'."""
        client = AsyncMock()
        client.get.side_effect = httpx.TimeoutException("timed out")
        scanner = MonitoringScanner(FAKE_TOKEN)
        result = await scanner.get_monitoring_status("123", client, asyncio.Semaphore(1))
        assert result == "unknown"

    @pytest.mark.asyncio
    async def test_network_error_returns_unknown(self):
        """Network error must return 'unknown', not 'missing'."""
        client = AsyncMock()
        client.get.side_effect = httpx.NetworkError("connection refused")
        scanner = MonitoringScanner(FAKE_TOKEN)
        result = await scanner.get_monitoring_status("123", client, asyncio.Semaphore(1))
        assert result == "unknown"

    @pytest.mark.asyncio
    async def test_null_data_field_returns_missing(self):
        """API returning null for the 'data' field must not raise — treated as no metrics."""
        client = AsyncMock()
        client.get.return_value = _resp(200, [], data_value=None)
        scanner = MonitoringScanner(FAKE_TOKEN)
        result = await scanner.get_monitoring_status("123", client, asyncio.Semaphore(1))
        assert result == "missing"

    @pytest.mark.asyncio
    async def test_passes_correct_params_to_api(self):
        client = AsyncMock()
        client.get.return_value = _resp(200, [])
        scanner = MonitoringScanner(FAKE_TOKEN)
        await scanner.get_monitoring_status("42", client, asyncio.Semaphore(1))
        call_kwargs = client.get.call_args
        params = call_kwargs.kwargs.get("params", {})
        assert params["host_id"] == "42"
        assert "start" in params
        assert "end" in params
        assert params["end"] > params["start"]


# ── scan_all_droplets_monitoring ───────────────────────────────────────────────

class TestScanAllDroplets:

    DROPLETS = [
        {"id": "111", "name": "web-01"},
        {"id": "222", "name": "db-01"},
        {"id": "333", "name": "app-01"},
    ]

    def _mock_client_ctx(self, mock_class, side_effect_fn):
        """Wire up AsyncClient as an async context manager returning a mock client."""
        mock_client = AsyncMock()
        mock_client.get.side_effect = side_effect_fn
        mock_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_class.return_value.__aexit__ = AsyncMock(return_value=False)
        return mock_client

    @pytest.mark.asyncio
    async def test_empty_list_returns_empty_without_api_call(self):
        scanner = MonitoringScanner(FAKE_TOKEN)
        result = await scanner.scan_all_droplets_monitoring([])
        assert result == []

    @pytest.mark.asyncio
    @patch("monitoring_scanner.httpx.AsyncClient")
    async def test_returns_correct_structure_for_single_droplet(self, mock_class):
        async def _side_effect(url, *, params=None, **kw):
            return _resp(200, [METRIC_ENTRY])

        self._mock_client_ctx(mock_class, _side_effect)
        scanner = MonitoringScanner(FAKE_TOKEN)
        results = await scanner.scan_all_droplets_monitoring([self.DROPLETS[0]])

        assert len(results) == 1
        assert results[0]["droplet_id"] == "111"
        assert results[0]["droplet_name"] == "web-01"
        assert results[0]["monitoring_status"] == "enabled"

    @pytest.mark.asyncio
    @patch("monitoring_scanner.httpx.AsyncClient")
    async def test_enabled_and_missing_counts(self, mock_class):
        # 111 → enabled, 222 → missing, 333 → enabled
        async def _side_effect(url, *, params=None, **kw):
            host_id = (params or {}).get("host_id", "")
            entries = [METRIC_ENTRY] if host_id in ("111", "333") else []
            return _resp(200, entries)

        self._mock_client_ctx(mock_class, _side_effect)
        scanner = MonitoringScanner(FAKE_TOKEN)
        results = await scanner.scan_all_droplets_monitoring(self.DROPLETS)

        assert len(results) == 3
        enabled = [r for r in results if r["monitoring_status"] == "enabled"]
        missing = [r for r in results if r["monitoring_status"] == "missing"]
        assert len(enabled) == 2
        assert len(missing) == 1
        assert missing[0]["droplet_name"] == "db-01"

    @pytest.mark.asyncio
    @patch("monitoring_scanner.httpx.AsyncClient")
    async def test_rate_limit_marks_status_unknown(self, mock_class):
        """429 from the API must mark the droplet as 'unknown', not 'missing'."""
        async def _side_effect(url, *, params=None, **kw):
            return _resp(429, [])

        self._mock_client_ctx(mock_class, _side_effect)
        scanner = MonitoringScanner(FAKE_TOKEN)
        results = await scanner.scan_all_droplets_monitoring([self.DROPLETS[0]])

        assert len(results) == 1
        assert results[0]["monitoring_status"] == "unknown"

    @pytest.mark.asyncio
    @patch("monitoring_scanner.httpx.AsyncClient")
    async def test_mixed_statuses_all_three_states(self, mock_class):
        """One enabled, one missing, one 429 → all three states represented."""
        async def _side_effect(url, *, params=None, **kw):
            host_id = (params or {}).get("host_id", "")
            if host_id == "111":
                return _resp(200, [METRIC_ENTRY])
            if host_id == "222":
                return _resp(200, [])
            return _resp(429, [])  # 333

        self._mock_client_ctx(mock_class, _side_effect)
        scanner = MonitoringScanner(FAKE_TOKEN)
        results = await scanner.scan_all_droplets_monitoring(self.DROPLETS)

        statuses = {r["droplet_id"]: r["monitoring_status"] for r in results}
        assert statuses["111"] == "enabled"
        assert statuses["222"] == "missing"
        assert statuses["333"] == "unknown"

    @pytest.mark.asyncio
    @patch("monitoring_scanner.httpx.AsyncClient")
    async def test_auth_error_propagates(self, mock_class):
        async def _side_effect(url, *, params=None, **kw):
            return _resp(401, [])

        self._mock_client_ctx(mock_class, _side_effect)
        scanner = MonitoringScanner(FAKE_TOKEN)
        with pytest.raises(ValueError):
            await scanner.scan_all_droplets_monitoring([self.DROPLETS[0]])

    @pytest.mark.asyncio
    @patch("monitoring_scanner.httpx.AsyncClient")
    async def test_network_error_marks_status_unknown(self, mock_class):
        """Unexpected exception in gather marks the droplet as 'unknown', not 'missing'."""
        async def _side_effect(url, *, params=None, **kw):
            raise httpx.NetworkError("refused")

        self._mock_client_ctx(mock_class, _side_effect)
        scanner = MonitoringScanner(FAKE_TOKEN)
        results = await scanner.scan_all_droplets_monitoring([self.DROPLETS[0]])

        assert len(results) == 1
        assert results[0]["monitoring_status"] == "unknown"
        assert results[0]["droplet_name"] == "web-01"

    @pytest.mark.asyncio
    @patch("monitoring_scanner.httpx.AsyncClient")
    async def test_all_disabled_returns_all_missing(self, mock_class):
        async def _side_effect(url, *, params=None, **kw):
            return _resp(200, [])

        self._mock_client_ctx(mock_class, _side_effect)
        scanner = MonitoringScanner(FAKE_TOKEN)
        results = await scanner.scan_all_droplets_monitoring(self.DROPLETS)

        assert all(r["monitoring_status"] == "missing" for r in results)
        assert len(results) == 3

    @pytest.mark.asyncio
    @patch("monitoring_scanner.httpx.AsyncClient")
    async def test_all_enabled_returns_all_enabled(self, mock_class):
        async def _side_effect(url, *, params=None, **kw):
            return _resp(200, [METRIC_ENTRY])

        self._mock_client_ctx(mock_class, _side_effect)
        scanner = MonitoringScanner(FAKE_TOKEN)
        results = await scanner.scan_all_droplets_monitoring(self.DROPLETS)

        assert all(r["monitoring_status"] == "enabled" for r in results)
        assert len(results) == 3
