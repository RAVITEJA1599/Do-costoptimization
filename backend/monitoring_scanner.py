"""
Fleet Health Scanner.

Checks Droplet monitoring agent status plus memory and disk utilisation
by querying the DigitalOcean Monitoring metrics API.

Status detection (all droplets, 1 call each):
    GET /v2/monitoring/metrics/droplet/cpu  — 6-hour window
    A non-empty result array means the agent is installed and reporting.

Utilisation metrics (enabled droplets only, skipped when coverage_only=True):
    Memory: GET /v2/monitoring/metrics/droplet/memory_available  (byte-valued)
          + GET /v2/monitoring/metrics/droplet/memory_total       (byte-valued)
          → memory_pct = (1 − available_bytes / total_bytes) × 100
          NOTE: memory_free is NOT used — Linux keeps almost no truly "free" RAM;
                spare pages are used for disk cache.  memory_available already
                subtracts reclaimable cache, matching what DO Insights reports.
    Disk:   GET /v2/monitoring/metrics/droplet/filesystem_free    (bytes free per partition)
          + GET /v2/monitoring/metrics/droplet/filesystem_size    (bytes total per partition)
          → disk_pct = max over partitions of (1 − free / size) × 100
          NOTE: filesystem_utilization does NOT exist in the DO API (returns 404).

Environment detection (name segments + tags, no extra API call):
    "PROD" | "DEV" | "QA" | "STAGING" | "unknown"

Usage — Fleet Health endpoint (full metrics):
    scanner = MonitoringScanner(token)
    results = await scanner.scan_all_droplets_monitoring(droplet_dicts)

Usage — analysis pipeline (status only, no extra API calls):
    results = await scanner.scan_all_droplets_monitoring(droplet_dicts, coverage_only=True)
"""
import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

_DO_API_BASE = "https://api.digitalocean.com/v2"
_REQUEST_TIMEOUT = 15   # seconds per call — short so a hung call doesn't block the pipeline
_CONCURRENCY = 5        # lower burst rate to stay under DO's 5 000 req/hour limit
_MAX_RETRY_SLEEP = 30   # cap the retry-after sleep so scans don't hang for a full window reset

# Lowercase keyword → canonical environment label
_ENV_MAP: Dict[str, str] = {
    "prod":        "PROD",
    "production":  "PROD",
    "dr":          "DR",
    "dev":         "DEV",
    "development": "DEV",
    "qa":          "QA",
    "test":        "TEST",
    "testing":     "TEST",
    "staging":     "STAGING",
    "stage":       "STAGING",
    "stg":         "STAGING",
    "uat":         "UAT",
    "demo":        "DEMO",
    "poc":         "POC",
    "backup":      "BACKUP",
}


def _detect_environment(name: str, tags: Optional[List[str]] = None) -> str:
    """
    Infer environment from droplet tags (checked first) then name segments.

    Tags take precedence because they are explicit.  Name segments are split on
    [-_.  ] so "SD-StoreWeb-PROD" → ["SD", "StoreWeb", "PROD"] → "PROD".

    Returns one of: "PROD", "DEV", "QA", "STAGING", "unknown".
    """
    for tag in (tags or []):
        env = _ENV_MAP.get(tag.lower())
        if env:
            return env

    # Replace all common separators with a space, then split
    normalized = name.replace("-", " ").replace("_", " ").replace(".", " ")
    for segment in normalized.split():
        env = _ENV_MAP.get(segment.lower())
        if env:
            return env

    return "unknown"


class MonitoringScanner:
    def __init__(self, token: str) -> None:
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def get_monitoring_status(
        self,
        droplet_id: str,
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
    ) -> str:
        """
        Return the monitoring status for a Droplet:
            "enabled"  — agent installed and reporting CPU metrics
            "missing"  — HTTP 200 with empty result (agent absent or not sending data)
            "unknown"  — API rate-limit (429), timeout, network error, or any other
                         transient failure; the true status cannot be determined

        Raises ValueError on HTTP 401 (invalid DigitalOcean API token) so callers
        can propagate an auth error rather than silently marking droplets unknown.
        """
        end_ts = int(time.time())
        start_ts = end_ts - 6 * 3600
        retry_delay = 0

        for attempt in range(3):
            if retry_delay:
                await asyncio.sleep(retry_delay)
                retry_delay = 0

            async with semaphore:
                try:
                    resp = await client.get(
                        f"{_DO_API_BASE}/monitoring/metrics/droplet/cpu",
                        headers=self._headers,
                        params={"host_id": droplet_id, "start": start_ts, "end": end_ts},
                        timeout=_REQUEST_TIMEOUT,
                    )

                    if resp.status_code == 401:
                        raise ValueError("Invalid DigitalOcean API token")

                    if resp.status_code == 429:
                        retry_delay = min(int(resp.headers.get("retry-after", "10")), _MAX_RETRY_SLEEP)
                        logger.warning(
                            "Rate limit checking monitoring for droplet %s — retry in %ds (attempt %d/3)",
                            droplet_id, retry_delay, attempt + 1,
                        )
                        continue  # release semaphore, sleep at top of next iteration

                    if resp.status_code != 200:
                        logger.warning(
                            "Monitoring API returned HTTP %s for droplet %s — status unknown",
                            resp.status_code, droplet_id,
                        )
                        return "unknown"

                    body = resp.json()
                    data_section = body.get("data") or {}
                    result = data_section.get("result", [])
                    return "enabled" if len(result) > 0 else "missing"

                except ValueError:
                    raise
                except httpx.TimeoutException:
                    logger.warning(
                        "Timeout checking monitoring for droplet %s — status unknown", droplet_id
                    )
                    return "unknown"
                except httpx.NetworkError as exc:
                    logger.warning(
                        "Network error checking monitoring for droplet %s: %s — status unknown",
                        droplet_id, exc,
                    )
                    return "unknown"

        logger.warning("Rate limit exhausted for droplet %s monitoring check — status unknown", droplet_id)
        return "unknown"

    async def _fetch_metric_series(
        self,
        droplet_id: str,
        endpoint: str,
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
    ) -> Optional[List[Dict]]:
        """
        Fetch the raw ``result`` list from a DO monitoring metrics endpoint.

        Returns the list of series dicts on HTTP 200 with non-empty data, or None
        on any failure (non-200, empty result, timeout, network error).

        Non-200 responses are logged at WARNING (404 from a wrong endpoint name will
        appear in production logs).  Empty results are logged at DEBUG.
        """
        end_ts = int(time.time())
        start_ts = end_ts - 6 * 3600
        retry_delay = 0

        for attempt in range(3):
            if retry_delay:
                await asyncio.sleep(retry_delay)
                retry_delay = 0

            async with semaphore:
                try:
                    resp = await client.get(
                        f"{_DO_API_BASE}{endpoint}",
                        headers=self._headers,
                        params={"host_id": droplet_id, "start": start_ts, "end": end_ts},
                        timeout=_REQUEST_TIMEOUT,
                    )

                    if resp.status_code == 429:
                        retry_delay = min(int(resp.headers.get("retry-after", "10")), _MAX_RETRY_SLEEP)
                        logger.warning(
                            "Rate limit on %s droplet %s — retry in %ds (attempt %d/3)",
                            endpoint, droplet_id, retry_delay, attempt + 1,
                        )
                        continue  # release semaphore, sleep at top of next iteration

                    if resp.status_code != 200:
                        logger.warning(
                            "Metric %s returned HTTP %s for droplet %s — skipping",
                            endpoint, resp.status_code, droplet_id,
                        )
                        return None

                    body = resp.json()
                    result = (body.get("data") or {}).get("result", [])
                    if not result:
                        logger.debug(
                            "Metric %s returned empty result for droplet %s "
                            "(agent installed but no data yet)",
                            endpoint, droplet_id,
                        )
                        return None

                    return result

                except httpx.TimeoutException:
                    logger.debug(
                        "Timeout fetching metric %s for droplet %s — skipping", endpoint, droplet_id
                    )
                    return None
                except httpx.NetworkError as exc:
                    logger.debug(
                        "Network error fetching metric %s for droplet %s: %s", endpoint, droplet_id, exc
                    )
                    return None
                except Exception as exc:
                    logger.debug(
                        "Unexpected error fetching metric %s for droplet %s: %s", endpoint, droplet_id, exc
                    )
                    return None

        logger.warning("Rate limit exhausted for %s droplet %s — no data", endpoint, droplet_id)
        return None

    async def _get_metric_pct(
        self,
        droplet_id: str,
        endpoint: str,
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
    ) -> Optional[float]:
        """
        Return the latest value across all result series for a single-value metric endpoint.

        Used for memory_available, memory_total, etc. where the API returns one series
        whose values are already in the desired unit (bytes or percent).

        Returns the most-recent value across all series via max(), or None on any failure.
        """
        result = await self._fetch_metric_series(droplet_id, endpoint, client, semaphore)
        if result is None:
            return None

        values: List[float] = []
        for series in result:
            raw = series.get("values", [])
            if raw:
                try:
                    values.append(float(raw[-1][1]))
                except (IndexError, TypeError, ValueError):
                    pass

        return max(values) if values else None

    async def _get_memory_pct(
        self,
        droplet_id: str,
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
    ) -> Optional[float]:
        """
        Compute memory utilisation as (1 − available / total) × 100.

        DO has no direct memory_utilization_percent endpoint.  memory_available is used
        (not memory_free) because Linux reclaims page-cache memory on demand — a droplet
        that is 95% "not-free" may only be 25% truly utilised.  memory_available already
        accounts for reclaimable cache and matches what DO Insights reports.

        Returns None when either endpoint fails, returns empty data, or total_bytes is zero.
        """
        avail_b, total_b = await asyncio.gather(
            self._get_metric_pct(droplet_id, "/monitoring/metrics/droplet/memory_available", client, semaphore),
            self._get_metric_pct(droplet_id, "/monitoring/metrics/droplet/memory_total", client, semaphore),
        )
        if avail_b is None or total_b is None or total_b == 0.0:
            return None
        return (1.0 - avail_b / total_b) * 100.0

    async def _get_disk_pct(
        self,
        droplet_id: str,
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
    ) -> Optional[float]:
        """
        Compute disk utilisation as max over partitions of (1 − free / size) × 100.

        filesystem_utilization does NOT exist in the DO API (returns 404).  The byte-value
        endpoints filesystem_free and filesystem_size are fetched in parallel; series are
        matched by their metric labels (device + mountpoint + fstype) and the most-stressed
        partition's percentage is returned — the operationally correct alarm signal.

        Returns None when either endpoint fails or no matched partition pairs are found.
        """
        free_result, size_result = await asyncio.gather(
            self._fetch_metric_series(
                droplet_id, "/monitoring/metrics/droplet/filesystem_free", client, semaphore
            ),
            self._fetch_metric_series(
                droplet_id, "/monitoring/metrics/droplet/filesystem_size", client, semaphore
            ),
        )

        if not free_result or not size_result:
            return None

        def _series_map(result: List[Dict]) -> Dict[frozenset, float]:
            """Map (metric-labels minus host_id) → last-sample value."""
            m: Dict[frozenset, float] = {}
            for series in result:
                key = frozenset(
                    (k, v) for k, v in series.get("metric", {}).items() if k != "host_id"
                )
                vals = series.get("values", [])
                if vals:
                    try:
                        m[key] = float(vals[-1][1])
                    except (IndexError, TypeError, ValueError):
                        pass
            return m

        free_map = _series_map(free_result)
        size_map = _series_map(size_result)

        pcts: List[float] = []
        for key, free_b in free_map.items():
            total_b = size_map.get(key)
            if total_b is not None and total_b > 0:
                pcts.append((1.0 - free_b / total_b) * 100.0)

        if pcts:
            logger.debug(
                "Disk utilization for droplet %s: %d partition(s), values=%s max=%.1f%%",
                droplet_id, len(pcts), [round(p, 1) for p in pcts], max(pcts),
            )

        return max(pcts) if pcts else None

    async def scan_all_droplets_monitoring(
        self,
        droplets: List[Dict[str, Any]],
        coverage_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Check monitoring status and (optionally) memory + disk utilisation for every Droplet.

        Args:
            droplets:      List of dicts with at least ``id``, ``name``, and optionally
                           ``tags`` keys (the normalised resource dicts from DigitalOceanScanner).
            coverage_only: When True, only the monitoring agent status is checked (1 API call
                           per droplet, memory_percent and disk_percent are None).  Set True in
                           the analysis pipeline where metric values would be discarded anyway.
                           Default False fetches memory + disk for every enabled droplet
                           (4 extra parallel calls per enabled droplet: 2 memory + 2 disk).

        Returns (per droplet):
            {
              "droplet_id":        str,
              "droplet_name":      str,
              "monitoring_status": "enabled" | "missing" | "unknown",
              "memory_percent":    float | None,   # (1 - available/total) * 100
              "disk_percent":      float | None,   # max(1 - free/size) * 100 across partitions
              "environment":       "PROD" | "DEV" | "QA" | "STAGING" | "unknown",
            }

        Raises:
            ValueError: if the DigitalOcean API token is invalid (HTTP 401).
        """
        if not droplets:
            return []

        semaphore = asyncio.Semaphore(_CONCURRENCY)
        async with httpx.AsyncClient() as client:
            tasks = [self._check_one(d, client, semaphore, coverage_only) for d in droplets]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        out: List[Dict[str, Any]] = []
        for droplet, result in zip(droplets, results):
            did = str(droplet.get("id", ""))
            dname = droplet.get("name", "unknown")
            if isinstance(result, ValueError):
                raise result
            if isinstance(result, Exception):
                logger.warning(
                    "Monitoring check failed for %s (%s): %s — marking unknown",
                    dname,
                    did,
                    result,
                )
                out.append({
                    "droplet_id": did,
                    "droplet_name": dname,
                    "monitoring_status": "unknown",
                    "memory_percent": None,
                    "disk_percent": None,
                    "environment": _detect_environment(dname, droplet.get("tags")),
                })
            else:
                out.append(result)

        return out

    async def _check_one(
        self,
        droplet: Dict[str, Any],
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
        coverage_only: bool = False,
    ) -> Dict[str, Any]:
        did = str(droplet.get("id", ""))
        dname = droplet.get("name", "unknown")
        tags: List[str] = droplet.get("tags") or []
        environment = _detect_environment(dname, tags)

        status = await self.get_monitoring_status(did, client, semaphore)

        # Skip metric calls when agent is absent/unknown (nothing to fetch) or caller
        # only needs agent status (analysis pipeline).
        if coverage_only or status != "enabled":
            return {
                "droplet_id": did,
                "droplet_name": dname,
                "monitoring_status": status,
                "memory_percent": None,
                "disk_percent": None,
                "environment": environment,
            }

        # Agent is confirmed present — fetch memory and disk in parallel.
        # Each helper acquires its own semaphore slots independently; no double-holding.
        mem_pct, disk_pct = await asyncio.gather(
            self._get_memory_pct(did, client, semaphore),
            self._get_disk_pct(did, client, semaphore),
        )

        return {
            "droplet_id": did,
            "droplet_name": dname,
            "monitoring_status": status,
            "memory_percent": mem_pct,
            "disk_percent": disk_pct,
            "environment": environment,
        }
