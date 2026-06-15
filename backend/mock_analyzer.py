"""
Rule-based cost analyzer used when CLAUDE_API_KEY is not configured.

Inspects the actual resource inventory (same data that would go to Claude)
and generates findings using DigitalOcean's published pricing.  The findings
include real doctl commands populated with the actual resource IDs so they
are immediately actionable.

Same public interface as AIAnalyzer: async analyze(project_name, resources, resource_count).
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── DigitalOcean pricing (USD/month) ─────────────────────────────────────────
_PRICE_FLOATING_IP = 4.0        # unassigned reserved IP
_PRICE_LB = 12.0                # per load balancer
_PRICE_VOLUME_PER_GB = 0.10     # block storage
_PRICE_SNAPSHOT_PER_GB = 0.06   # snapshots
_PRICE_VCPU_ESTIMATE = 6.0      # rough $/vCPU/month for oversized droplet calc


class MockAnalyzer:
    """
    Deterministic, rule-based analyzer.  Covers the same categories as the
    Claude system prompt so the UI and report structure look identical.
    """

    async def analyze(
        self,
        project_name: str,
        resources: List[Dict[str, Any]],
        resource_count: Dict[str, int],
        model_name: str = "",
        preliminary_findings: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        total = resource_count.get("total", len(resources))
        logger.info(
            "[MOCK] Analyzing %d resources for project '%s' "
            "(Claude API key not configured — using rule-based analysis)",
            total, project_name,
        )

        # Group by resource type for easy iteration
        by_type: Dict[str, List[Dict]] = {}
        for r in resources:
            by_type.setdefault(r.get("type", "unknown"), []).append(r)

        findings: List[Dict[str, Any]] = []
        findings += self._unattached_volumes(by_type.get("volume", []))
        findings += self._unassigned_floating_ips(by_type.get("floating_ip", []))
        findings += self._idle_load_balancers(by_type.get("load_balancer", []))
        findings += self._snapshot_sprawl(by_type.get("snapshot", []))
        findings += self._inactive_droplets(by_type.get("droplet", []))
        findings += self._oversized_droplets(by_type.get("droplet", []))

        # Append monitoring findings from the rule engine (confirmed-missing droplets only)
        if preliminary_findings:
            for pf in preliminary_findings:
                if pf.get("issue", "").startswith("DigitalOcean Monitoring Agent not enabled"):
                    findings.append(_finding(
                        name=pf["resource_name"],
                        rtype="droplet",
                        severity=pf.get("severity", "high"),
                        issue=pf["issue"],
                        monthly=0,
                        recommendation=pf["recommendation"],
                        steps=[
                            "Connect to the Droplet via SSH",
                            "Run: curl -sSL https://repos.sonar.digitalocean.com/install.sh | sudo bash",
                            "Verify agent is running: sudo systemctl status do-agent",
                            "Metrics will appear in the DigitalOcean Monitoring dashboard within a few minutes",
                        ],
                    ))

        monthly = sum(_dollars(f["monthly_savings"]) for f in findings)
        annual = monthly * 12

        logger.info("[MOCK] Done — %d findings, $%.0f/month potential savings", len(findings), monthly)

        return {
            "summary": {
                "total_resources": total,
                "issues_found": len(findings),
                "estimated_monthly_savings": f"${monthly:.0f}",
                "estimated_annual_savings": f"${annual:.0f}",
            },
            "findings": findings,
            "input_tokens": 0,
            "output_tokens": 0,
        }

    # ── Rule checks ───────────────────────────────────────────────────────────

    def _unattached_volumes(self, volumes: List[Dict]) -> List[Dict]:
        out = []
        for v in volumes:
            if v.get("attached_to"):
                continue
            size = v.get("size_gb", 0)
            mo = round(size * _PRICE_VOLUME_PER_GB, 2)
            vid = v.get("id", "<volume-id>")
            out.append(_finding(
                name=v.get("name", "unnamed-volume"),
                rtype="volume",
                severity="high",
                issue=f"Volume is {size} GB and unattached to any Droplet — costing ${mo:.2f}/month",
                monthly=mo,
                recommendation="Delete the volume or attach it to an active Droplet",
                steps=[
                    f"Confirm the volume is no longer needed: doctl compute volume get {vid}",
                    "Create a final snapshot if data may be needed: doctl compute volume-snapshot create "
                    f"{vid} --snapshot-name {v.get('name', 'vol')}-backup",
                    f"Delete the volume: doctl compute volume delete {vid} --force",
                ],
            ))
        return out

    def _unassigned_floating_ips(self, fips: List[Dict]) -> List[Dict]:
        out = []
        for fip in fips:
            if fip.get("assigned_to"):
                continue
            ip = fip.get("ip", "<ip>")
            out.append(_finding(
                name=ip,
                rtype="floating_ip",
                severity="high",
                issue="Reserved IP is not assigned to any Droplet and costs $4/month",
                monthly=_PRICE_FLOATING_IP,
                recommendation="Assign the IP to an active Droplet or release it",
                steps=[
                    f"Check whether the IP is still in use: doctl compute floating-ip get {ip}",
                    f"Assign to a Droplet: doctl compute floating-ip-action assign {ip} <droplet-id>",
                    f"Or release it: doctl compute floating-ip delete {ip} --force",
                ],
            ))
        return out

    def _idle_load_balancers(self, lbs: List[Dict]) -> List[Dict]:
        out = []
        for lb in lbs:
            count = len(lb.get("assigned_droplet_ids", []))
            lbid = lb.get("id", "<lb-id>")
            if count == 0:
                out.append(_finding(
                    name=lb.get("name", "unnamed-lb"),
                    rtype="load_balancer",
                    severity="high",
                    issue="Load balancer has no attached Droplets and costs $12/month",
                    monthly=_PRICE_LB,
                    recommendation="Attach Droplets or delete the unused load balancer",
                    steps=[
                        f"Review configuration: doctl compute load-balancer get {lbid}",
                        f"Attach Droplets: doctl compute load-balancer add-droplets {lbid} --droplet-ids <ids>",
                        f"Or delete: doctl compute load-balancer delete {lbid} --force",
                    ],
                ))
            elif count == 1:
                out.append(_finding(
                    name=lb.get("name", "unnamed-lb"),
                    rtype="load_balancer",
                    severity="medium",
                    issue="Load balancer has only 1 Droplet — routing traffic directly via DNS may save $12/month",
                    monthly=_PRICE_LB,
                    recommendation="Add more Droplets to justify the cost, or remove the LB and use direct DNS",
                    steps=[
                        f"Check traffic volume: doctl compute load-balancer get {lbid}",
                        "If traffic does not require load balancing, update DNS A records to point to the Droplet IP",
                        f"Delete the load balancer once DNS propagates: doctl compute load-balancer delete {lbid} --force",
                    ],
                ))
        return out

    def _snapshot_sprawl(self, snapshots: List[Dict]) -> List[Dict]:
        # Group by the resource_type of the snapshot (droplet / volume)
        by_rtype: Dict[str, List[Dict]] = {}
        for s in snapshots:
            by_rtype.setdefault(s.get("resource_type", "droplet"), []).append(s)

        out = []
        for rtype, snaps in by_rtype.items():
            old = _old_snapshots(snaps, days=30)

            if len(old) >= 3:
                total_gb = sum(s.get("size_gb", 0) for s in old)
                mo = round(total_gb * _PRICE_SNAPSHOT_PER_GB, 2)
                out.append(_finding(
                    name=f"{rtype.capitalize()} Snapshots ({len(old)} older than 30 days)",
                    rtype="snapshot",
                    severity="medium",
                    issue=f"{len(old)} {rtype} snapshots older than 30 days occupying {total_gb} GB (${mo:.2f}/month)",
                    monthly=mo,
                    recommendation="Delete snapshots older than 30 days; keep the 2–3 most recent per resource",
                    steps=[
                        f"List all {rtype} snapshots: doctl compute snapshot list --resource-type {rtype}",
                        "Sort by creation date and identify outdated ones",
                        "Delete each old snapshot: doctl compute snapshot delete <snapshot-id> --force",
                        "Automate retention: keep only the last 3 snapshots per resource",
                    ],
                ))
            elif len(snaps) > 5:
                total_gb = sum(s.get("size_gb", 0) for s in snaps)
                mo = round(total_gb * _PRICE_SNAPSHOT_PER_GB, 2)
                out.append(_finding(
                    name=f"{rtype.capitalize()} Snapshots ({len(snaps)} total)",
                    rtype="snapshot",
                    severity="low",
                    issue=f"{len(snaps)} {rtype} snapshots with no clear retention policy ({total_gb} GB, ${mo:.2f}/month)",
                    monthly=mo,
                    recommendation="Review snapshots and implement a retention policy (keep last 3)",
                    steps=[
                        f"List snapshots: doctl compute snapshot list --resource-type {rtype}",
                        "Delete unnecessary snapshots: doctl compute snapshot delete <id> --force",
                    ],
                ))
        return out

    def _inactive_droplets(self, droplets: List[Dict]) -> List[Dict]:
        out = []
        for d in droplets:
            if d.get("status") not in ("off", "archive"):
                continue
            vcpus = d.get("vcpus", 1)
            mo = max(4, int(vcpus * _PRICE_VCPU_ESTIMATE))
            did = d.get("id", "<droplet-id>")
            out.append(_finding(
                name=d.get("name", "unnamed-droplet"),
                rtype="droplet",
                severity="high",
                issue=f"Droplet is powered {d.get('status')} but still billed at ~${mo}/month ({vcpus} vCPU)",
                monthly=mo,
                recommendation="Snapshot and destroy the Droplet, or resize it down before restarting",
                steps=[
                    f"Create a final snapshot: doctl compute droplet-action snapshot {did} "
                    f"--snapshot-name {d.get('name', 'droplet')}-final",
                    f"Destroy the Droplet: doctl compute droplet delete {did} --force",
                    "If the workload resumes, restore from snapshot into a smaller Droplet size",
                ],
            ))
        return out

    def _oversized_droplets(self, droplets: List[Dict]) -> List[Dict]:
        out = []
        for d in droplets:
            if d.get("status") != "active":
                continue
            vcpus = d.get("vcpus", 0)
            mem_gb = round(d.get("memory", 0) / 1024, 0)
            did = d.get("id", "<droplet-id>")

            if vcpus >= 8:
                mo_current = int(vcpus * _PRICE_VCPU_ESTIMATE)
                mo_smaller = int((vcpus // 2) * _PRICE_VCPU_ESTIMATE)
                savings = mo_current - mo_smaller
                out.append(_finding(
                    name=d.get("name", "unnamed-droplet"),
                    rtype="droplet",
                    severity="medium",
                    issue=f"Large Droplet ({vcpus} vCPUs / {mem_gb:.0f} GB RAM) — verify utilization before next billing cycle",
                    monthly=savings,
                    recommendation=f"Monitor CPU/memory for 7 days; resize down to {vcpus // 2} vCPUs if utilization is below 40%",
                    steps=[
                        f"Check current metrics: doctl compute droplet get {did}",
                        f"Power off to resize: doctl compute droplet-action power-off {did}",
                        f"Resize to half the vCPUs: doctl compute droplet-action resize {did} --size s-{vcpus // 2}vcpu-{max(1, int(mem_gb // 2))}gb",
                        f"Power back on: doctl compute droplet-action power-on {did}",
                    ],
                ))
            elif vcpus >= 4:
                tags = d.get("tags", [])
                is_prod = any("prod" in t.lower() for t in tags)
                if not is_prod:
                    out.append(_finding(
                        name=d.get("name", "unnamed-droplet"),
                        rtype="droplet",
                        severity="low",
                        issue=f"Droplet ({vcpus} vCPUs / {mem_gb:.0f} GB) has no 'production' tag — may be over-provisioned for dev/staging",
                        monthly=12,
                        recommendation="Review workload requirements and downsize if this is a non-production server",
                        steps=[
                            f"Review Droplet details: doctl compute droplet get {did}",
                            f"Power off: doctl compute droplet-action power-off {did}",
                            f"Resize to a smaller plan: doctl compute droplet-action resize {did} --size s-2vcpu-4gb",
                            f"Power on: doctl compute droplet-action power-on {did}",
                        ],
                    ))
        return out


# ── Utilities ─────────────────────────────────────────────────────────────────

def _finding(
    *,
    name: str,
    rtype: str,
    severity: str,
    issue: str,
    monthly: float,
    recommendation: str,
    steps: List[str],
) -> Dict[str, Any]:
    mo = round(monthly, 2)
    return {
        "resource_name": name,
        "resource_type": rtype,
        "severity": severity,
        "issue": issue,
        "monthly_savings": f"${mo:.0f}",
        "annual_savings": f"${mo * 12:.0f}",
        "recommendation": recommendation,
        "remediation_steps": steps,
    }


def _dollars(s: str) -> float:
    try:
        return float(str(s).replace("$", "").replace(",", "").strip())
    except (ValueError, AttributeError):
        return 0.0


def _old_snapshots(snaps: List[Dict], days: int) -> List[Dict]:
    out = []
    now = datetime.now(timezone.utc)
    for s in snaps:
        created = s.get("created_at", "")
        if not created:
            continue
        try:
            age = (now - datetime.fromisoformat(created.replace("Z", "+00:00"))).days
            if age > days:
                out.append(s)
        except (ValueError, TypeError):
            pass
    return out
