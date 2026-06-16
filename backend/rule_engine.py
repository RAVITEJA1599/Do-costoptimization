"""
Rule Engine: deterministic pre-AI cost analysis.
Detects obvious cost issues before Claude to reduce token usage and hallucinations.
Each rule returns zero or more finding dicts (no savings estimates — Claude adds those).

Environment detection
─────────────────────
Rules that could be false positives on production systems (over-provisioned droplets,
large DB clusters) use _detect_effective_environment() before emitting a finding.
Detection is tag-first, name-segment fallback, case-insensitive.

Suppressed environments: PROD, DR — large instances are operationally justified.
All other environments (DEV, QA, STAGING, UAT, DEMO, TEST, POC, BACKUP, UNKNOWN)
still receive the finding because over-provisioning is actionable in those contexts.
"""
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, FrozenSet, List, Optional

logger = logging.getLogger(__name__)

# Maps a lowercase tag value or name segment to a canonical environment label.
_ENV_MAP: Dict[str, str] = {
    "prod":        "PROD",
    "production":  "PROD",
    "dev":         "DEV",
    "development": "DEV",
    "qa":          "QA",
    "staging":     "STAGING",
    "stage":       "STAGING",
    "stg":         "STAGING",
    "uat":         "UAT",
    "demo":        "DEMO",
    "test":        "TEST",
    "testing":     "TEST",
    "poc":         "POC",
    "dr":          "DR",
    "backup":      "BACKUP",
}

# Environments where large instances are operationally justified.
# Over-provisioning and large-DB warnings are suppressed for these.
_PROD_LIKE_ENVS: FrozenSet[str] = frozenset({"PROD", "DR"})

# Separator characters used to split a resource name into segments.
_NAME_SEP = re.compile(r"[-_.\s]+")


def _detect_effective_environment(
    name: str,
    tags: Optional[List[str]] = None,
) -> str:
    """
    Return the effective environment for a resource.

    Priority:
      1. First matching tag (explicit intent — highest priority)
      2. First matching segment of the resource name (tag-free fallback)
      3. "UNKNOWN" when neither yields a match

    Segment splitting: name is split on [-_. ] so "SD-Dms-PROD" yields
    ["SD", "Dms", "PROD"] and the third segment maps to "PROD".

    Returns one of:
      PROD | DR | DEV | QA | STAGING | UAT | DEMO | TEST | POC | BACKUP | UNKNOWN
    """
    for tag in (tags or []):
        env = _ENV_MAP.get(tag.lower())
        if env:
            return env

    for segment in _NAME_SEP.split(name):
        env = _ENV_MAP.get(segment.lower())
        if env:
            return env

    return "UNKNOWN"


class RuleEngine:
    def run(
        self,
        resources: List[Dict[str, Any]],
        resource_count: Dict[str, int],
        monitoring_data: Optional[List[Dict[str, Any]]] = None,
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
        if monitoring_data:
            findings += self._rule_no_monitoring(monitoring_data)

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
        """
        Flag large droplets (≥8 vCPU or ≥16 GB RAM) that may be over-provisioned.

        Suppressed for PROD and DR environments — large instances are expected there.
        Uses effective environment detection (tag-first, name-fallback) so that a
        droplet named SD-Dms-PROD is correctly classified as PROD even without an
        explicit 'production' tag.
        """
        out = []
        for d in droplets:
            vcpus = d.get("vcpus", 0)
            memory = d.get("memory", 0)
            if not (vcpus >= 8 or memory >= 16384):
                continue
            env = _detect_effective_environment(d.get("name", ""), d.get("tags"))
            if env in _PROD_LIKE_ENVS:
                continue
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
        """
        Flag managed database clusters with ≥3 nodes that may be over-sized.

        Suppressed for PROD and DR environments where multi-node HA is expected.
        Environment is detected from the database name (DO managed databases have
        no tags in the resource model).
        """
        out = []
        for db in databases:
            nodes = db.get("num_nodes", 0)
            if nodes < 3:
                continue
            env = _detect_effective_environment(db.get("name", ""), db.get("tags"))
            if env in _PROD_LIKE_ENVS:
                continue
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

    def _rule_no_monitoring(self, monitoring_data: List[Dict]) -> List[Dict]:
        out = []
        for d in monitoring_data:
            # Only flag confirmed-missing; "unknown" means the check failed transiently
            if d.get("monitoring_status") == "missing":
                out.append(self._f(
                    resource_name=d.get("droplet_name", "unknown"),
                    resource_type="droplet",
                    severity="high",
                    issue=(
                        "DigitalOcean Monitoring Agent not enabled — CPU, memory, and disk metrics "
                        "are unavailable; alerts cannot be configured for this Droplet"
                    ),
                    recommendation=(
                        "Install the DigitalOcean Monitoring Agent via SSH: "
                        "curl -sSL https://repos.sonar.digitalocean.com/install.sh | sudo bash. "
                        "See: https://docs.digitalocean.com/products/monitoring/quickstart/"
                    ),
                    confidence="high",
                ))
        return out
