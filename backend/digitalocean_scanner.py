import httpx
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from models import (
    Droplet, Volume, Snapshot, ManagedDatabase,
    LoadBalancer, FloatingIP
)

logger = logging.getLogger(__name__)

DO_API_BASE = "https://api.digitalocean.com/v2"
REQUEST_TIMEOUT = 30
PAGE_SIZE = 200  # DigitalOcean API maximum per_page value


class DigitalOceanAPIError(Exception):
    pass


class RateLimitError(DigitalOceanAPIError):
    pass


class InvalidTokenError(DigitalOceanAPIError):
    pass


class ProjectNotFoundError(DigitalOceanAPIError):
    pass


class DigitalOceanScanner:
    def __init__(self, token: str):
        self.token = token
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        self.client = None

    async def __aenter__(self):
        self.client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.client:
            await self.client.aclose()

    async def _request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Make a single API request with error handling."""
        url = f"{DO_API_BASE}{endpoint}"

        if not self.client:
            self.client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT)

        try:
            response = await self.client.request(
                method,
                url,
                headers=self.headers,
                **kwargs
            )

            if response.status_code == 401:
                raise InvalidTokenError("Invalid DigitalOcean API Token")

            if response.status_code == 429:
                raise RateLimitError("DigitalOcean API rate limit exceeded")

            if response.status_code == 404:
                raise ProjectNotFoundError("Project not found")

            response.raise_for_status()
            return response.json()

        except httpx.TimeoutException:
            raise DigitalOceanAPIError("Request timeout - DigitalOcean API is taking too long")
        except httpx.NetworkError as e:
            raise DigitalOceanAPIError(f"Network error: {str(e)}")

    async def _paginate(
        self,
        endpoint: str,
        list_key: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Collect every page of a paginated DigitalOcean list endpoint.

        Sends per_page=PAGE_SIZE (the API maximum of 200) on every request
        to minimise round-trips.  Pagination continues as long as the
        response contains a links.pages.next URL.

        Stops early if a page returns zero items (guards against infinite
        loops on malformed API responses).

        After all pages are collected, logs a WARNING if the fetched count
        does not match the API-reported meta.total — so count mismatches
        surface immediately in the application logs.
        """
        request_params: Dict[str, Any] = {
            **(params or {}),
            "per_page": PAGE_SIZE,
            "page": 1,
        }
        all_items: List[Dict[str, Any]] = []
        last_data: Dict[str, Any] = {}

        while True:
            last_data = await self._request("GET", endpoint, params=request_params)
            page_items: List[Dict[str, Any]] = last_data.get(list_key) or []
            all_items.extend(page_items)

            # Stop when there is no next-page link or the page was empty
            next_url = (last_data.get("links") or {}).get("pages", {}).get("next")
            if not next_url or not page_items:
                break

            request_params = {**request_params, "page": request_params["page"] + 1}
            logger.debug(
                f"Paginating {endpoint}: {len(all_items)} items so far, "
                f"fetching page {request_params['page']}"
            )

        api_total = (last_data.get("meta") or {}).get("total")
        logger.debug(
            f"Pagination complete for {endpoint}: {len(all_items)} items fetched"
            + (f" (API meta.total={api_total})" if api_total is not None else "")
        )
        if api_total is not None and api_total != len(all_items):
            logger.warning(
                f"Count mismatch on {endpoint}: fetched {len(all_items)}, "
                f"API meta.total={api_total}"
            )

        return all_items

    async def get_projects(self) -> List[Dict[str, Any]]:
        """Fetch all DigitalOcean Projects (all pages)."""
        try:
            raw = await self._paginate("/projects", "projects")
            return [
                {
                    "id": p.get("id"),
                    "name": p.get("name"),
                    "description": p.get("description", ""),
                    "is_default": p.get("is_default", False),
                    "created_at": p.get("created_at"),
                }
                for p in raw
            ]
        except Exception as e:
            logger.error(f"Error fetching projects: {e}")
            raise

    async def get_droplets(self, project_id: str) -> List[Droplet]:
        """Fetch all Droplets in a project (all pages)."""
        try:
            params = {"tag_name": f"project:{project_id}"} if project_id else {}
            raw = await self._paginate("/droplets", "droplets", params)
            return [
                Droplet(
                    id=str(d.get("id")),
                    name=d.get("name"),
                    region=d.get("region", {}).get("slug", "unknown"),
                    vcpus=d.get("vcpus", 0),
                    memory=d.get("memory", 0),
                    disk=d.get("disk", 0),
                    status=d.get("status", "unknown"),
                    tags=d.get("tags", []),
                    locked=d.get("locked", False),
                )
                for d in raw
            ]
        except Exception as e:
            logger.error(f"Error fetching droplets: {e}")
            raise

    async def get_volumes(self, project_id: str) -> List[Volume]:
        """Fetch all Block Storage Volumes in a project (all pages)."""
        try:
            params = {"tag_name": f"project:{project_id}"} if project_id else {}
            raw = await self._paginate("/volumes", "volumes", params)
            return [
                Volume(
                    id=v.get("id"),
                    name=v.get("name"),
                    size_gb=v.get("size_gigabytes", 0),
                    region=v.get("region", {}).get("slug", "unknown"),
                    attached_to=[str(d) for d in v.get("droplet_ids", [])],
                    status=v.get("status", "available"),
                )
                for v in raw
            ]
        except Exception as e:
            logger.error(f"Error fetching volumes: {e}")
            raise

    async def get_snapshots(self, project_id: str) -> List[Snapshot]:
        """Fetch all Snapshots in a project (all pages)."""
        try:
            params = {"tag_name": f"project:{project_id}"} if project_id else {}
            raw = await self._paginate("/snapshots", "snapshots", params)
            return [
                Snapshot(
                    id=s.get("id"),
                    name=s.get("name"),
                    created_at=s.get("created_at"),
                    resource_type=s.get("resource_type", "unknown"),
                    size_gb=int(s.get("size_gigabytes", 0)),
                )
                for s in raw
            ]
        except Exception as e:
            logger.error(f"Error fetching snapshots: {e}")
            raise

    async def get_managed_databases(self, project_id: str) -> List[ManagedDatabase]:
        """Fetch all Managed Databases in a project (all pages)."""
        try:
            params = {"tag_name": f"project:{project_id}"} if project_id else {}
            raw = await self._paginate("/databases", "databases", params)
            return [
                ManagedDatabase(
                    id=db.get("id"),
                    name=db.get("name"),
                    engine=db.get("engine", "unknown"),
                    version=db.get("version", "unknown"),
                    db_name=db.get("db_name"),
                    num_nodes=db.get("num_nodes", 1),
                    region=db.get("region", "unknown"),
                    status=db.get("status", "unknown"),
                )
                for db in raw
            ]
        except Exception as e:
            logger.error(f"Error fetching managed databases: {e}")
            raise

    async def get_load_balancers(self, project_id: str) -> List[LoadBalancer]:
        """Fetch all Load Balancers in a project (all pages)."""
        try:
            params = {"tag_name": f"project:{project_id}"} if project_id else {}
            raw = await self._paginate("/load_balancers", "load_balancers", params)
            return [
                LoadBalancer(
                    id=lb.get("id"),
                    name=lb.get("name"),
                    region=lb.get("region", {}).get("slug", "unknown"),
                    assigned_droplet_ids=[str(did) for did in lb.get("droplet_ids", [])],
                    status=lb.get("status", "unknown"),
                )
                for lb in raw
            ]
        except Exception as e:
            logger.error(f"Error fetching load balancers: {e}")
            raise

    async def get_floating_ips(self, project_id: str) -> List[FloatingIP]:
        """Fetch all Floating IPs in a project (all pages)."""
        try:
            params = {"tag_name": f"project:{project_id}"} if project_id else {}
            raw = await self._paginate("/floating_ips", "floating_ips", params)
            floating_ips = []
            for fip in raw:
                assigned_to = None
                if fip.get("droplet") and fip["droplet"].get("id"):
                    assigned_to = str(fip["droplet"]["id"])
                floating_ips.append(FloatingIP(
                    id=fip.get("ip"),
                    ip=fip.get("ip"),
                    region=fip.get("region", {}).get("slug", "unknown"),
                    assigned_to=assigned_to,
                    status="active" if assigned_to else "available",
                ))
            return floating_ips
        except Exception as e:
            logger.error(f"Error fetching floating IPs: {e}")
            raise

    async def analyze_project(self, project_id: str) -> Dict[str, Any]:
        """Fetch all resources for a project."""
        try:
            projects_data = await self._paginate("/projects", "projects")
            project = next((p for p in projects_data if p.get("id") == project_id), None)
            if not project:
                raise ProjectNotFoundError(f"Project {project_id} not found")

            project_name = project.get("name", "Unknown")

            droplets, volumes, snapshots, databases, load_balancers, floating_ips = \
                await self._fetch_all_resources(project_id)

            resources = (
                [d.dict() for d in droplets]
                + [v.dict() for v in volumes]
                + [s.dict() for s in snapshots]
                + [db.dict() for db in databases]
                + [lb.dict() for lb in load_balancers]
                + [fip.dict() for fip in floating_ips]
            )

            resource_count = {
                "droplets": len(droplets),
                "volumes": len(volumes),
                "snapshots": len(snapshots),
                "databases": len(databases),
                "load_balancers": len(load_balancers),
                "floating_ips": len(floating_ips),
                "total": len(resources),
            }

            return {
                "project_id": project_id,
                "project_name": project_name,
                "resources": resources,
                "resource_count": resource_count,
                "timestamp": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            logger.error(f"Error analyzing project {project_id}: {e}")
            raise

    async def _fetch_all_resources(self, project_id: str):
        """Fetch all resource types concurrently (each type fully paginated)."""
        import asyncio

        results = await asyncio.gather(
            self.get_droplets(project_id),
            self.get_volumes(project_id),
            self.get_snapshots(project_id),
            self.get_managed_databases(project_id),
            self.get_load_balancers(project_id),
            self.get_floating_ips(project_id),
            return_exceptions=True,
        )

        def safe_result(result):
            if isinstance(result, Exception):
                logger.warning(f"Error in resource fetch: {result}")
                return []
            return result

        return tuple(safe_result(r) for r in results)
