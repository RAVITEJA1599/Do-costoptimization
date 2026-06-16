"""
Tests for MonitoringScanner and _detect_environment.

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
from monitoring_scanner import MonitoringScanner, _detect_environment  # noqa: E402

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


def _fs_resp(partition_values: list) -> MagicMock:
    """Build a filesystem metric response with one series per partition.

    partition_values: list of (device, mountpoint, value) tuples.
    Matches the real DO API structure for filesystem_free / filesystem_size.
    """
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = {
        "status": "success",
        "data": {
            "resultType": "matrix",
            "result": [
                {
                    "metric": {
                        "device": device,
                        "fstype": "ext4",
                        "mountpoint": mountpoint,
                    },
                    "values": [[1700000000, str(value)]],
                }
                for device, mountpoint, value in partition_values
            ],
        },
    }
    return r


# ── _detect_environment ────────────────────────────────────────────────────────

class TestDetectEnvironment:

    def test_prod_from_name_dash_suffix(self):
        assert _detect_environment("SD-StoreWeb-PROD") == "PROD"

    def test_dev_from_name_dash_segment(self):
        assert _detect_environment("SD-Crm-DEV") == "DEV"

    def test_qa_from_name_dash_segment(self):
        assert _detect_environment("SD-Mozart2.0-QA") == "QA"

    def test_staging_from_name_segment(self):
        assert _detect_environment("SD-API-STAGING") == "STAGING"

    def test_stg_alias_for_staging(self):
        assert _detect_environment("backend-stg") == "STAGING"

    def test_unknown_when_no_keyword_found(self):
        assert _detect_environment("SD-ATHENA-BK") == "unknown"

    def test_case_insensitive_name(self):
        assert _detect_environment("sd-rabbitmq-prod") == "PROD"

    def test_underscore_separator(self):
        assert _detect_environment("web_server_production") == "PROD"

    def test_dot_separator(self):
        assert _detect_environment("api.service.dev") == "DEV"

    def test_tag_takes_precedence_over_name(self):
        """Explicit tag wins even when the name says otherwise."""
        assert _detect_environment("SD-Widget-DEV", tags=["prod"]) == "PROD"

    def test_tag_matching_is_case_insensitive(self):
        assert _detect_environment("droplet-1", tags=["Production"]) == "PROD"

    def test_empty_tags_list_falls_through_to_name(self):
        assert _detect_environment("SD-API-PROD", tags=[]) == "PROD"

    def test_unrelated_tags_fall_through_to_name(self):
        assert _detect_environment("SD-API-QA", tags=["web", "nginx"]) == "QA"

    def test_returns_unknown_for_empty_name_no_tags(self):
        assert _detect_environment("") == "unknown"

    def test_production_keyword(self):
        assert _detect_environment("my-production-server") == "PROD"

    def test_test_keyword_maps_to_qa(self):
        assert _detect_environment("SD-Worker-TEST") == "QA"


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


# ── _fetch_metric_series ───────────────────────────────────────────────────────

class TestFetchMetricSeries:
    ENDPOINT = "/monitoring/metrics/droplet/memory_available"

    @pytest.mark.asyncio
    async def test_returns_result_list_on_success(self):
        client = AsyncMock()
        client.get.return_value = _resp(200, [METRIC_ENTRY])
        scanner = MonitoringScanner(FAKE_TOKEN)
        result = await scanner._fetch_metric_series("123", self.ENDPOINT, client, asyncio.Semaphore(1))
        assert result == [METRIC_ENTRY]

    @pytest.mark.asyncio
    async def test_returns_none_on_404_and_logs_warning(self):
        """HTTP 404 (wrong endpoint name) must return None and emit a WARNING."""
        client = AsyncMock()
        client.get.return_value = _resp(404, [])
        scanner = MonitoringScanner(FAKE_TOKEN)
        with patch("monitoring_scanner.logger") as mock_logger:
            result = await scanner._fetch_metric_series("123", self.ENDPOINT, client, asyncio.Semaphore(1))
        assert result is None
        mock_logger.warning.assert_called_once()
        assert "404" in str(mock_logger.warning.call_args[0])

    @pytest.mark.asyncio
    async def test_returns_none_on_500_and_logs_warning(self):
        client = AsyncMock()
        client.get.return_value = _resp(500, [])
        scanner = MonitoringScanner(FAKE_TOKEN)
        with patch("monitoring_scanner.logger") as mock_logger:
            result = await scanner._fetch_metric_series("123", self.ENDPOINT, client, asyncio.Semaphore(1))
        assert result is None
        mock_logger.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_result_returns_none_and_logs_debug(self):
        """Empty result (agent installed but no data) must log at DEBUG, not WARNING."""
        client = AsyncMock()
        client.get.return_value = _resp(200, [])
        scanner = MonitoringScanner(FAKE_TOKEN)
        with patch("monitoring_scanner.logger") as mock_logger:
            result = await scanner._fetch_metric_series("123", self.ENDPOINT, client, asyncio.Semaphore(1))
        assert result is None
        mock_logger.warning.assert_not_called()
        mock_logger.debug.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_none_on_timeout(self):
        client = AsyncMock()
        client.get.side_effect = httpx.TimeoutException("timed out")
        scanner = MonitoringScanner(FAKE_TOKEN)
        result = await scanner._fetch_metric_series("123", self.ENDPOINT, client, asyncio.Semaphore(1))
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_network_error(self):
        client = AsyncMock()
        client.get.side_effect = httpx.NetworkError("refused")
        scanner = MonitoringScanner(FAKE_TOKEN)
        result = await scanner._fetch_metric_series("123", self.ENDPOINT, client, asyncio.Semaphore(1))
        assert result is None


# ── _get_metric_pct ────────────────────────────────────────────────────────────

class TestGetMetricPct:
    ENDPOINT = "/monitoring/metrics/droplet/memory_available"

    def _metric_resp(self, series_values: list) -> MagicMock:
        """Build a response with multiple result series."""
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = {
            "status": "success",
            "data": {
                "resultType": "matrix",
                "result": [
                    {"metric": {"device": f"vd{chr(97+i)}"}, "values": [[1700000000, str(v)]]}
                    for i, v in enumerate(series_values)
                ],
            },
        }
        return r

    @pytest.mark.asyncio
    async def test_returns_float_on_success(self):
        client = AsyncMock()
        client.get.return_value = self._metric_resp([72.4])
        scanner = MonitoringScanner(FAKE_TOKEN)
        result = await scanner._get_metric_pct("123", self.ENDPOINT, client, asyncio.Semaphore(1))
        assert result == pytest.approx(72.4)

    @pytest.mark.asyncio
    async def test_returns_max_across_series(self):
        """When multiple series are returned, max of last values is used."""
        client = AsyncMock()
        client.get.return_value = self._metric_resp([45.0, 92.3, 18.7])
        scanner = MonitoringScanner(FAKE_TOKEN)
        result = await scanner._get_metric_pct("123", self.ENDPOINT, client, asyncio.Semaphore(1))
        assert result == pytest.approx(92.3)

    @pytest.mark.asyncio
    async def test_returns_none_on_empty_result(self):
        client = AsyncMock()
        client.get.return_value = _resp(200, [])
        scanner = MonitoringScanner(FAKE_TOKEN)
        result = await scanner._get_metric_pct("123", self.ENDPOINT, client, asyncio.Semaphore(1))
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_rate_limit(self):
        client = AsyncMock()
        client.get.return_value = _resp(429, [])
        scanner = MonitoringScanner(FAKE_TOKEN)
        result = await scanner._get_metric_pct("123", self.ENDPOINT, client, asyncio.Semaphore(1))
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_server_error(self):
        client = AsyncMock()
        client.get.return_value = _resp(500, [])
        scanner = MonitoringScanner(FAKE_TOKEN)
        result = await scanner._get_metric_pct("123", self.ENDPOINT, client, asyncio.Semaphore(1))
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_timeout(self):
        client = AsyncMock()
        client.get.side_effect = httpx.TimeoutException("timed out")
        scanner = MonitoringScanner(FAKE_TOKEN)
        result = await scanner._get_metric_pct("123", self.ENDPOINT, client, asyncio.Semaphore(1))
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_network_error(self):
        client = AsyncMock()
        client.get.side_effect = httpx.NetworkError("refused")
        scanner = MonitoringScanner(FAKE_TOKEN)
        result = await scanner._get_metric_pct("123", self.ENDPOINT, client, asyncio.Semaphore(1))
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_null_data(self):
        client = AsyncMock()
        client.get.return_value = _resp(200, [], data_value=None)
        scanner = MonitoringScanner(FAKE_TOKEN)
        result = await scanner._get_metric_pct("123", self.ENDPOINT, client, asyncio.Semaphore(1))
        assert result is None


# ── _get_memory_pct ────────────────────────────────────────────────────────────

class TestGetMemoryPct:

    def _mem_resp(self, value: float) -> MagicMock:
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = {
            "status": "success",
            "data": {"resultType": "matrix", "result": [
                {"metric": {}, "values": [[1700000000, str(value)]]}
            ]},
        }
        return r

    @pytest.mark.asyncio
    async def test_computes_percentage_from_available_and_total(self):
        """(1 - available/total) * 100 — uses memory_available, not memory_free."""
        client = AsyncMock()
        avail_bytes = 6_212_792_320.0   # ~5.78 GB available (matches DO Insights behaviour)
        total_bytes = 8_318_173_184.0   # ~7.75 GB total

        def _side(url, *, params=None, **kw):
            if "memory_available" in url:
                return self._mem_resp(avail_bytes)
            return self._mem_resp(total_bytes)  # memory_total

        client.get.side_effect = _side
        scanner = MonitoringScanner(FAKE_TOKEN)
        result = await scanner._get_memory_pct("123", client, asyncio.Semaphore(10))
        expected = (1 - avail_bytes / total_bytes) * 100  # ≈ 25.3%
        assert result == pytest.approx(expected, rel=1e-4)

    @pytest.mark.asyncio
    async def test_does_not_use_memory_free(self):
        """Verify memory_available is called, not memory_free (which inflates Linux usage)."""
        client = AsyncMock()
        called_urls = []

        def _side(url, *, params=None, **kw):
            called_urls.append(url)
            return self._mem_resp(1_000_000_000.0)

        client.get.side_effect = _side
        scanner = MonitoringScanner(FAKE_TOKEN)
        await scanner._get_memory_pct("123", client, asyncio.Semaphore(10))

        assert any("memory_available" in u for u in called_urls), "memory_available not called"
        assert not any("memory_free" in u for u in called_urls), "memory_free must NOT be called"

    @pytest.mark.asyncio
    async def test_returns_none_when_available_fetch_fails(self):
        client = AsyncMock()

        def _side(url, *, params=None, **kw):
            if "memory_available" in url:
                return _resp(404, [])
            return self._mem_resp(1_000_000_000.0)

        client.get.side_effect = _side
        scanner = MonitoringScanner(FAKE_TOKEN)
        result = await scanner._get_memory_pct("123", client, asyncio.Semaphore(10))
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_total_fetch_fails(self):
        client = AsyncMock()

        def _side(url, *, params=None, **kw):
            if "memory_total" in url:
                return _resp(404, [])
            return self._mem_resp(6_000_000_000.0)

        client.get.side_effect = _side
        scanner = MonitoringScanner(FAKE_TOKEN)
        result = await scanner._get_memory_pct("123", client, asyncio.Semaphore(10))
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_total_is_zero(self):
        """Guard against division by zero."""
        client = AsyncMock()
        client.get.side_effect = lambda url, **kw: self._mem_resp(0.0)
        scanner = MonitoringScanner(FAKE_TOKEN)
        result = await scanner._get_memory_pct("123", client, asyncio.Semaphore(10))
        assert result is None

    @pytest.mark.asyncio
    async def test_100_percent_when_no_available_memory(self):
        """Edge case: available = 0 bytes → 100% utilised."""
        client = AsyncMock()

        def _side(url, *, params=None, **kw):
            if "memory_available" in url:
                return self._mem_resp(0.0)
            return self._mem_resp(1_000_000_000.0)

        client.get.side_effect = _side
        scanner = MonitoringScanner(FAKE_TOKEN)
        result = await scanner._get_memory_pct("123", client, asyncio.Semaphore(10))
        assert result == pytest.approx(100.0)


# ── _get_disk_pct ──────────────────────────────────────────────────────────────

class TestGetDiskPct:

    @pytest.mark.asyncio
    async def test_single_partition_computes_correctly(self):
        """Basic (1 - free/size) * 100 for a single partition."""
        client = AsyncMock()
        free_bytes = 11_893_231_616.0    # real value from SD-APP-MOZART-PROD
        size_bytes = 82_086_711_296.0

        def _side(url, *, params=None, **kw):
            if "filesystem_free" in url:
                return _fs_resp([("/dev/vda1", "/", free_bytes)])
            return _fs_resp([("/dev/vda1", "/", size_bytes)])  # filesystem_size

        client.get.side_effect = _side
        scanner = MonitoringScanner(FAKE_TOKEN)
        result = await scanner._get_disk_pct("123", client, asyncio.Semaphore(10))
        expected = (1 - free_bytes / size_bytes) * 100  # ≈ 85.5%
        assert result == pytest.approx(expected, rel=1e-4)

    @pytest.mark.asyncio
    async def test_multi_partition_returns_max(self):
        """When multiple partitions exist, the most-stressed one must be surfaced."""
        client = AsyncMock()

        partitions_free = [
            ("/dev/vda1", "/",      50_000_000_000.0),   # 50 GB free of 100 GB → 50%
            ("/dev/vda2", "/data",   5_000_000_000.0),   # 5 GB free of 100 GB → 95%
            ("/dev/vda3", "/tmp",   80_000_000_000.0),   # 80 GB free of 100 GB → 20%
        ]
        partitions_size = [
            ("/dev/vda1", "/",     100_000_000_000.0),
            ("/dev/vda2", "/data", 100_000_000_000.0),
            ("/dev/vda3", "/tmp",  100_000_000_000.0),
        ]

        def _side(url, *, params=None, **kw):
            if "filesystem_free" in url:
                return _fs_resp(partitions_free)
            return _fs_resp(partitions_size)

        client.get.side_effect = _side
        scanner = MonitoringScanner(FAKE_TOKEN)
        result = await scanner._get_disk_pct("123", client, asyncio.Semaphore(10))
        assert result == pytest.approx(95.0)

    @pytest.mark.asyncio
    async def test_returns_none_when_free_endpoint_fails(self):
        """404 on filesystem_free must return None — filesystem_utilization does not exist."""
        client = AsyncMock()

        def _side(url, *, params=None, **kw):
            if "filesystem_free" in url:
                return _resp(404, [])
            return _fs_resp([("/dev/vda1", "/", 82_086_711_296.0)])

        client.get.side_effect = _side
        scanner = MonitoringScanner(FAKE_TOKEN)
        result = await scanner._get_disk_pct("123", client, asyncio.Semaphore(10))
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_size_endpoint_fails(self):
        client = AsyncMock()

        def _side(url, *, params=None, **kw):
            if "filesystem_size" in url:
                return _resp(404, [])
            return _fs_resp([("/dev/vda1", "/", 11_893_231_616.0)])

        client.get.side_effect = _side
        scanner = MonitoringScanner(FAKE_TOKEN)
        result = await scanner._get_disk_pct("123", client, asyncio.Semaphore(10))
        assert result is None

    @pytest.mark.asyncio
    async def test_does_not_call_filesystem_utilization(self):
        """filesystem_utilization returns 404; must never be called."""
        client = AsyncMock()
        called_urls = []

        def _side(url, *, params=None, **kw):
            called_urls.append(url)
            if "filesystem_free" in url:
                return _fs_resp([("/dev/vda1", "/", 10_000_000_000.0)])
            return _fs_resp([("/dev/vda1", "/", 80_000_000_000.0)])

        client.get.side_effect = _side
        scanner = MonitoringScanner(FAKE_TOKEN)
        await scanner._get_disk_pct("123", client, asyncio.Semaphore(10))

        assert not any("filesystem_utilization" in u for u in called_urls)
        assert any("filesystem_free" in u for u in called_urls)
        assert any("filesystem_size" in u for u in called_urls)

    @pytest.mark.asyncio
    async def test_returns_none_when_size_is_zero(self):
        """Guard against division by zero on a partition with size 0."""
        client = AsyncMock()

        def _side(url, *, params=None, **kw):
            if "filesystem_free" in url:
                return _fs_resp([("/dev/vda1", "/", 0.0)])
            return _fs_resp([("/dev/vda1", "/", 0.0)])  # size = 0

        client.get.side_effect = _side
        scanner = MonitoringScanner(FAKE_TOKEN)
        result = await scanner._get_disk_pct("123", client, asyncio.Semaphore(10))
        assert result is None

    @pytest.mark.asyncio
    async def test_skips_unmatched_partitions(self):
        """Only partitions present in both free and size responses are counted."""
        client = AsyncMock()

        def _side(url, *, params=None, **kw):
            if "filesystem_free" in url:
                # two partitions
                return _fs_resp([
                    ("/dev/vda1", "/", 10_000_000_000.0),
                    ("/dev/vda2", "/data", 5_000_000_000.0),
                ])
            # size only has one matching partition
            return _fs_resp([("/dev/vda1", "/", 100_000_000_000.0)])

        client.get.side_effect = _side
        scanner = MonitoringScanner(FAKE_TOKEN)
        result = await scanner._get_disk_pct("123", client, asyncio.Semaphore(10))
        # Only /dev/vda1 matched → (1 - 10/100) * 100 = 90%
        assert result == pytest.approx(90.0)


# ── scan_all_droplets_monitoring ───────────────────────────────────────────────

class TestScanAllDroplets:

    DROPLETS = [
        {"id": "111", "name": "web-01-PROD", "tags": []},
        {"id": "222", "name": "db-01-DEV",   "tags": []},
        {"id": "333", "name": "app-01-QA",   "tags": []},
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
        r = results[0]
        assert r["droplet_id"] == "111"
        assert r["droplet_name"] == "web-01-PROD"
        assert r["monitoring_status"] == "enabled"
        assert r["environment"] == "PROD"
        assert "memory_percent" in r
        assert "disk_percent" in r

    @pytest.mark.asyncio
    @patch("monitoring_scanner.httpx.AsyncClient")
    async def test_environment_detected_from_name(self, mock_class):
        async def _side_effect(url, *, params=None, **kw):
            return _resp(200, [])

        self._mock_client_ctx(mock_class, _side_effect)
        scanner = MonitoringScanner(FAKE_TOKEN)
        results = await scanner.scan_all_droplets_monitoring(self.DROPLETS)

        envs = {r["droplet_id"]: r["environment"] for r in results}
        assert envs["111"] == "PROD"
        assert envs["222"] == "DEV"
        assert envs["333"] == "QA"

    @pytest.mark.asyncio
    @patch("monitoring_scanner.httpx.AsyncClient")
    async def test_environment_detected_from_tags(self, mock_class):
        async def _side_effect(url, *, params=None, **kw):
            return _resp(200, [])

        self._mock_client_ctx(mock_class, _side_effect)
        scanner = MonitoringScanner(FAKE_TOKEN)
        droplet = {"id": "999", "name": "my-droplet", "tags": ["production"]}
        results = await scanner.scan_all_droplets_monitoring([droplet])

        assert results[0]["environment"] == "PROD"

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
        assert missing[0]["droplet_name"] == "db-01-DEV"

    @pytest.mark.asyncio
    @patch("monitoring_scanner.httpx.AsyncClient")
    async def test_missing_droplets_have_null_metrics(self, mock_class):
        """Droplets with missing agent must have None for memory and disk."""
        async def _side_effect(url, *, params=None, **kw):
            return _resp(200, [])  # all missing

        self._mock_client_ctx(mock_class, _side_effect)
        scanner = MonitoringScanner(FAKE_TOKEN)
        results = await scanner.scan_all_droplets_monitoring([self.DROPLETS[0]])

        assert results[0]["monitoring_status"] == "missing"
        assert results[0]["memory_percent"] is None
        assert results[0]["disk_percent"] is None

    @pytest.mark.asyncio
    @patch("monitoring_scanner.httpx.AsyncClient")
    async def test_coverage_only_skips_metric_calls(self, mock_class):
        """coverage_only=True must make exactly 1 CPU call per droplet (no memory/disk)."""
        call_urls: list = []

        async def _side_effect(url, *, params=None, **kw):
            call_urls.append(url)
            return _resp(200, [METRIC_ENTRY])  # all enabled

        self._mock_client_ctx(mock_class, _side_effect)
        scanner = MonitoringScanner(FAKE_TOKEN)
        results = await scanner.scan_all_droplets_monitoring([self.DROPLETS[0]], coverage_only=True)

        # Exactly 1 call (CPU only)
        assert len(call_urls) == 1
        assert "cpu" in call_urls[0]
        # Metric fields must be None even though agent is enabled
        assert results[0]["monitoring_status"] == "enabled"
        assert results[0]["memory_percent"] is None
        assert results[0]["disk_percent"] is None

    @pytest.mark.asyncio
    @patch("monitoring_scanner.httpx.AsyncClient")
    async def test_full_scan_makes_5_calls_per_enabled_droplet(self, mock_class):
        """Default (coverage_only=False) must fetch memory×2 + disk×2 when agent is enabled.

        Correct endpoints:
          cpu (status) + memory_available + memory_total + filesystem_free + filesystem_size = 5
        """
        call_urls: list = []

        def _build_fs_resp(value: float):
            r = MagicMock()
            r.status_code = 200
            r.json.return_value = {
                "status": "success",
                "data": {"resultType": "matrix", "result": [
                    {"metric": {"device": "/dev/vda1", "fstype": "ext4", "mountpoint": "/"},
                     "values": [[1700000000, str(value)]]}
                ]},
            }
            return r

        async def _side_effect(url, *, params=None, **kw):
            call_urls.append(url)
            if "memory_available" in url:
                return _resp(200, [{"metric": {}, "values": [[1700000000, "6000000000"]]}])
            if "memory_total" in url:
                return _resp(200, [{"metric": {}, "values": [[1700000000, "8000000000"]]}])
            if "filesystem_free" in url:
                return _build_fs_resp(20_000_000_000.0)
            if "filesystem_size" in url:
                return _build_fs_resp(100_000_000_000.0)
            return _resp(200, [METRIC_ENTRY])  # cpu

        self._mock_client_ctx(mock_class, _side_effect)
        scanner = MonitoringScanner(FAKE_TOKEN)
        results = await scanner.scan_all_droplets_monitoring([self.DROPLETS[0]])

        assert len(call_urls) == 5
        assert any("cpu" in u for u in call_urls)
        assert any("memory_available" in u for u in call_urls)
        assert any("memory_total" in u for u in call_urls)
        assert any("filesystem_free" in u for u in call_urls)
        assert any("filesystem_size" in u for u in call_urls)
        # memory_pct = (1 - 6GB/8GB) * 100 = 25.0%
        assert results[0]["memory_percent"] == pytest.approx(25.0)
        # disk_pct = (1 - 20GB/100GB) * 100 = 80.0%
        assert results[0]["disk_percent"] == pytest.approx(80.0)

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
        assert results[0]["droplet_name"] == "web-01-PROD"

    @pytest.mark.asyncio
    @patch("monitoring_scanner.httpx.AsyncClient")
    async def test_all_disabled_returns_all_missing(self, mock_class):
        async def _side_effect(url, *, params=None, **kw):
            return _resp(200, [])

        self._mock_client_ctx(mock_class, _side_effect)
        scanner = MonitoringScanner(FAKE_TOKEN)
        results = await scanner.scan_all_droplets_monitoring(self.DROPLETS)

        assert all(r["monitoring_status"] == "missing" for r in results)
        assert all(r["memory_percent"] is None for r in results)
        assert all(r["disk_percent"] is None for r in results)
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
