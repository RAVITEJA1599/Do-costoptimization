"""
Monitoring Coverage Scanner.

Checks whether the DigitalOcean Monitoring Agent is enabled on each Droplet by
querying the CPU metrics endpoint for a recent 6-hour window.  An empty result
array means the agent is absent or not reporting.

Usage inside the analysis pipeline (pass already-fetched droplet dicts):
    monitoring_data = await MonitoringScanner(token).scan_all_droplets_monitoring(droplet_dicts)

Usage for the standalone coverage endpoint:
    scanner = MonitoringScanner(token)
    results = await scanner.scan_all_droplets_monitoring(droplet_dicts)
"""
import asyncio
import logging
import time
from typing import Any, Dict, List

import httpx

logger = logging.getLogger(__name__)

_DO_API_BASE = "https://api.digitalocean.com/v2"
_REQUEST_TIMEOUT = 15   # seconds per droplet — short so a hung call doesn't block the pipeline
_CONCURRENCY = 5        # max simultaneous monitoring API calls


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
                    logger.warning(
                        "Monitoring API rate limit hit for droplet %s — status unknown", droplet_id
                    )
                    return "unknown"
                if resp.status_code != 200:
                    logger.warning(
                        "Monitoring API returned HTTP %s for droplet %s — status unknown",
                        resp.status_code,
                        droplet_id,
                    )
                    return "unknown"

                body = resp.json()
                # Use `or {}` to handle a null "data" field gracefully
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
                    droplet_id,
                    exc,
                )
                return "unknown"

    async def scan_all_droplets_monitoring(
        self,
        droplets: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Check monitoring status for every Droplet in the list.

        Args:
            droplets: List of dicts with at least ``id`` and ``name`` keys
                      (the normalised resource dicts produced by DigitalOceanScanner).

        Returns:
            [
                {"droplet_id": "123", "droplet_name": "web-01", "monitoring_status": "enabled"},
                {"droplet_id": "456", "droplet_name": "db-01",  "monitoring_status": "missing"},
                {"droplet_id": "789", "droplet_name": "app-01", "monitoring_status": "unknown"},
                ...
            ]

        Raises:
            ValueError: if the DigitalOcean API token is invalid (HTTP 401).
        """
        if not droplets:
            return []

        semaphore = asyncio.Semaphore(_CONCURRENCY)
        async with httpx.AsyncClient() as client:
            tasks = [self._check_one(d, client, semaphore) for d in droplets]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        out: List[Dict[str, Any]] = []
        for droplet, result in zip(droplets, results):
            did = str(droplet.get("id", ""))
            dname = droplet.get("name", "unknown")
            if isinstance(result, ValueError):
                raise result
            if isinstance(result, Exception):
                # Unexpected exception (e.g. JSON decode error) — status cannot be determined
                logger.warning(
                    "Monitoring check failed for %s (%s): %s — marking unknown",
                    dname,
                    did,
                    result,
                )
                out.append({"droplet_id": did, "droplet_name": dname, "monitoring_status": "unknown"})
            else:
                out.append(result)

        return out

    async def _check_one(
        self,
        droplet: Dict[str, Any],
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
    ) -> Dict[str, Any]:
        did = str(droplet.get("id", ""))
        dname = droplet.get("name", "unknown")
        status = await self.get_monitoring_status(did, client, semaphore)
        return {"droplet_id": did, "droplet_name": dname, "monitoring_status": status}
