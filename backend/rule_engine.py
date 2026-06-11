"""
Rule Engine: deterministic pre-AI cost analysis.
Detects obvious cost issues before Claude to reduce token usage and hallucinations.
Each rule returns zero or more finding dicts (no savings estimates — Claude adds those).
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class RuleEngine:
    def run(
        self,
        resources: List[Dict[str, Any]],
        resource_count: Dict[str, int],
    ) -> Dict[str, Any]:
        """
        Run all rules against the normalised resource inventory.
        Returns preliminary findings list + summary counts.
        """
        by_type: Dict[str, List[Dict]] = {}
        for r in resources:
            by_type.setdefault(r.get("type", "unknown"), []).append(r)

        findings: List[Dict[str, Any]] = []
        findings += self._rule_unattached_volumes(by_type.get("volume", []))
        findings += self._rule_unassigned_floating_ips(by_type.get("floating_ip", []))
        findings += self._rule_old_snapshots(by_type.get("snapshot", []))
        findings += self._rule_snapshot_sprawl(by_type.get("snapshot", []))
        findings += self._rule_powered_off_droplets(by_type.get("droplet", []))
        findings += self._rule_over_provisioned_droplets(by_type.get("droplet", []))
        findings += self._rule_large_databases(by_type.get("database", []))
        findings += self._rule_idle_load_balancers(by_type.get("load_balancer", []))

        logger.info(
            f"Rule Engine: {len(findings)} preliminary findings "
            f"from {resource_count.get('total', len(resources))} resources"
        )
        return {
            "summary": {
                "resources_scanned": resource_count.get("total", len(resources)),
                "preliminary_findings": len(findings),
            },
            "findings": findings,
        }

    # ── helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _f(resource_name: str, resource_type: str, severity: str,
           issue: str, recommendation: str, confidence: str) -> Dict[str, Any]:
        return {
            "resource_name": resource_name,
            "resource_type": resource_type,
            "severity": severity,
            "issue": issue,
            "recommendation": recommendation,
            "confidence": confidence,
        }

    # ── rules ──────────────────────────────────────────────────────────────────

    def _rule_unattached_volumes(self, volumes: List[Dict]) -> List[Dict]:
        out = []
        for v in volumes:
            if not v.get("attached_to"):
                out.append(self._f(
                    resource_name=v.get("name", "unknown"),
                    resource_type="volume",
                    severity="high",
                    issue=(
                        f"Unattached volume ({v.get('size_gb', 0)} GB) — "
                        "billed at $0.10/GB/month but not mounted to any Droplet"
                    ),
                    recommendation="Delete the volume if data is no longer needed, or attach it to an active Droplet",
                    confidence="high",
                ))
        return out

    def _rule_unassigned_floating_ips(self, fips: List[Dict]) -> List[Dict]:
        out = []
        for fip in fips:
            if not fip.get("assigned_to"):
                out.append(self._f(
                    resource_name=fip.get("ip", "unknown"),
                    resource_type="floating_ip",
                    severity="high",
                    issue="Unassigned Floating IP — reserved but not attached to any Droplet (billed at $4/month)",
                    recommendation="Delete the Floating IP or assign it to an active Droplet",
                    confidence="high",
                ))
        return out

    def _rule_old_snapshots(self, snapshots: List[Dict]) -> List[Dict]:
        out = []
        now = datetime.now(timezone.utc)
        for s in snapshots:
            raw = s.get("created_at")
            if not raw:
                continue
            try:
                created = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                age = (now - created).days
                if age > 90:
                    out.append(self._f(
                        resource_name=s.get("name", "unknown"),
                        resource_type="snapshot",
                        severity="medium",
                        issue=(
                            f"Old snapshot ({age} days old, {s.get('size_gb', 0)} GB) — "
                            "snapshots older than 90 days are likely stale"
                        ),
                        recommendation="Review whether this snapshot is still needed; delete if obsolete",
                        confidence="high",
                    ))
            except (ValueError, TypeError):
                pass
        return out

    def _rule_snapshot_sprawl(self, snapshots: List[Dict]) -> List[Dict]:
        counts: Dict[str, int] = {}
        for s in snapshots:
            rtype = s.get("resource_type", "snapshot")
            counts[rtype] = counts.get(rtype, 0) + 1

        out = []
        for rtype, count in counts.items():
            if count > 5:
                label = "Droplet" if "droplet" in rtype else "Volume" if "volume" in rtype else rtype
                out.append(self._f(
                    resource_name=f"{label} snapshots ({rtype})",
                    resource_type="snapshot",
                    severity="medium",
                    issue=(
                        f"Snapshot sprawl: {count} {rtype.replace('_', ' ')}s detected "
                        "without a clear retention policy"
                    ),
                    recommendation="Define a snapshot retention policy; keep only the last 3–5 snapshots per resource",
                    confidence="medium",
                ))
        return out

    def _rule_powered_off_droplets(self, droplets: List[Dict]) -> List[Dict]:
        out = []
        for d in droplets:
            if d.get("status") == "off":
                mem_gb = round(d.get("memory", 0) / 1024, 1)
                out.append(self._f(
                    resource_name=d.get("name", "unknown"),
                    resource_type="droplet",
                    severity="high",
                    issue=(
                        f"Powered-off Droplet ({d.get('vcpus')} vCPU / {mem_gb} GB RAM) — "
                        "still billed at full price even when off"
                    ),
                    recommendation="Delete the Droplet if no longer needed, or snapshot-and-delete to save costs",
                    confidence="high",
                ))
        return out

    def _rule_over_provisioned_droplets(self, droplets: List[Dict]) -> List[Dict]:
        out = []
        for d in droplets:
            vcpus = d.get("vcpus", 0)
            memory = d.get("memory", 0)
            if vcpus >= 8 or memory >= 16384:
                mem_gb = round(memory / 1024, 1)
                out.append(self._f(
                    resource_name=d.get("name", "unknown"),
                    resource_type="droplet",
                    severity="medium",
                    issue=(
                        f"Potentially over-provisioned Droplet ({vcpus} vCPU / {mem_gb} GB RAM) — "
                        "large instance that may be underutilised (utilisation metrics not available)"
                    ),
                    recommendation="Review CPU and memory utilisation; downsize if average usage is consistently below 30%",
                    confidence="low",
                ))
        return out

    def _rule_large_databases(self, databases: List[Dict]) -> List[Dict]:
        out = []
        for db in databases:
            nodes = db.get("num_nodes", 0)
            if nodes >= 3:
                out.append(self._f(
                    resource_name=db.get("name", "unknown"),
                    resource_type="database",
                    severity="medium",
                    issue=(
                        f"Large Managed Database cluster ({nodes} nodes, "
                        f"{db.get('engine')} {db.get('version')}) — "
                        "multi-node clusters are expensive and may be oversized for the workload"
                    ),
                    recommendation="Review if high-availability is required; consider fewer nodes for non-production environments",
                    confidence="medium",
                ))
        return out

    def _rule_idle_load_balancers(self, load_balancers: List[Dict]) -> List[Dict]:
        out = []
        for lb in load_balancers:
            if not lb.get("assigned_droplet_ids"):
                out.append(self._f(
                    resource_name=lb.get("name", "unknown"),
                    resource_type="load_balancer",
                    severity="high",
                    issue="Idle Load Balancer with no attached Droplets — billed at $12/month with no traffic handled",
                    recommendation="Delete the Load Balancer if unused, or attach active Droplets to justify the cost",
                    confidence="high",
                ))
        return out
