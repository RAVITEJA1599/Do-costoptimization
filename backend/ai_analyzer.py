import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

import anthropic
from rule_engine import _detect_effective_environment

logger = logging.getLogger(__name__)

CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
MAX_TOKENS = int(os.getenv("CLAUDE_MAX_TOKENS", "4096"))

SYSTEM_PROMPT = """You are a Senior Cloud FinOps Engineer specializing in DigitalOcean infrastructure.

Analyze the provided resource inventory and identify cost inefficiencies. Focus on:

1. **Over-provisioned Droplets** — resources sized far above what the workload needs.
   Each Droplet in the inventory includes an `env=` field (e.g. env=PROD, env=DEV).
   This is pre-computed from the droplet's DigitalOcean tags and name segments — it is authoritative.
   Do NOT flag a Droplet as over-provisioned when env=PROD or env=DR.
   Large instances in production and disaster-recovery environments are expected and intentional.
2. **Unattached Volumes** — block storage not mounted to any Droplet (billed at $0.10/GB/month)
3. **Stale Snapshots** — snapshots older than 30 days that are accumulating storage costs
4. **Snapshot Sprawl** — more than 3 snapshots per resource without a clear retention policy
5. **Idle Load Balancers** — load balancers with 0–1 attached Droplets (billed at $12/month)
6. **Unassigned Floating IPs** — reserved IPs not attached to any Droplet (billed at $4/month)
7. **Oversized Managed Databases** — high-tier clusters with low utilization signals (many nodes, large plans)
8. **Locked/Inactive Droplets** — Droplets in "off" or "archive" state still being billed

Use real DigitalOcean pricing when estimating savings:
- Basic Droplets: $4–$96/month depending on size
- Premium Droplets: $12–$192/month
- Block Volumes: $0.10/GB/month
- Snapshots: $0.06/GB/month
- Unassigned Floating IPs: $4/month each
- Load Balancers: $12/month each
- Managed Databases: $15–$300+/month depending on plan

Severity guidelines:
- **high**: Resource is clearly unused or grossly over-provisioned — immediate action warranted
- **medium**: Resource may be over-provisioned or has moderate waste — review recommended
- **low**: Minor inefficiency or potential optimization — optional improvement

You MUST return ONLY a valid JSON object. No markdown fences, no explanation text, no code blocks. Exactly this schema:

{
  "summary": {
    "total_resources": <integer — total count of all resources analyzed>,
    "issues_found": <integer — number of findings>,
    "estimated_monthly_savings": "<dollar amount e.g. $125>",
    "estimated_annual_savings": "<dollar amount e.g. $1500>"
  },
  "findings": [
    {
      "resource_name": "<resource name>",
      "resource_type": "<droplet|volume|snapshot|database|load_balancer|floating_ip>",
      "severity": "<high|medium|low>",
      "issue": "<concise problem description>",
      "monthly_savings": "<dollar amount e.g. $24>",
      "annual_savings": "<dollar amount e.g. $288>",
      "recommendation": "<single clear action>",
      "remediation_steps": [
        "<step 1>",
        "<step 2>",
        "<step 3>"
      ]
    }
  ]
}

If no issues are found, return findings as an empty array and savings as "$0"."""


class AIAnalysisError(Exception):
    pass


class AIAuthError(AIAnalysisError):
    pass


class AIRateLimitError(AIAnalysisError):
    pass


class AITimeoutError(AIAnalysisError):
    pass


class AIMalformedResponseError(AIAnalysisError):
    pass


class AIEmptyResponseError(AIAnalysisError):
    pass


class AIAnalyzer:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self._client: Optional[anthropic.AsyncAnthropic] = None

    @property
    def client(self) -> anthropic.AsyncAnthropic:
        if not self._client:
            self._client = anthropic.AsyncAnthropic(api_key=self.api_key)
        return self._client

    async def analyze(
        self,
        project_name: str,
        resources: List[Dict[str, Any]],
        resource_count: Dict[str, int],
        model_name: str = CLAUDE_MODEL,
        preliminary_findings: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Analyze resources for cost optimization using Claude.

        Args:
            project_name: Human-readable project name
            resources: Normalized resource list from DigitalOceanScanner
            resource_count: Per-type resource counts
            model_name: Claude model ID to use (defaults to CLAUDE_MODEL env var)
            preliminary_findings: Optional findings from the Rule Engine pre-pass

        Returns:
            Parsed AI analysis dict with summary, findings, and token usage
        """
        user_message = self._build_inventory_prompt(
            project_name, resources, resource_count, preliminary_findings
        )

        logger.info(
            f"Sending {resource_count.get('total', len(resources))} resources "
            f"from project '{project_name}' to {model_name} "
            f"({len(preliminary_findings or [])} rule-engine findings pre-loaded)"
        )

        raw_response, tokens = await self._call_claude(user_message, model_name)
        result = self._parse_response(raw_response, total_resources=resource_count.get("total", len(resources)))

        result["input_tokens"] = tokens["input_tokens"]
        result["output_tokens"] = tokens["output_tokens"]

        logger.info(
            f"Claude analysis complete: {result['summary']['issues_found']} issues found, "
            f"estimated savings {result['summary']['estimated_monthly_savings']}/month, "
            f"tokens: {tokens['input_tokens']} input + {tokens['output_tokens']} output"
        )

        return result

    def _build_inventory_prompt(
        self,
        project_name: str,
        resources: List[Dict[str, Any]],
        resource_count: Dict[str, int],
        preliminary_findings: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Format resource inventory + rule-engine findings into a structured prompt."""
        lines: List[str] = [
            f"Project: {project_name}",
            f"Total Resources: {resource_count.get('total', len(resources))}",
            "",
            "Resource Inventory:",
            "=" * 50,
        ]

        # Group resources by type for readability
        by_type: Dict[str, List[Dict]] = {}
        for r in resources:
            rtype = r.get("type", "unknown")
            by_type.setdefault(rtype, []).append(r)

        # Droplets
        if "droplet" in by_type:
            lines.append(f"\nDROPLETS ({len(by_type['droplet'])} total):")
            for d in by_type["droplet"]:
                memory_gb = round(d.get("memory", 0) / 1024, 1)
                tags = ", ".join(d.get("tags", [])) or "none"
                env = _detect_effective_environment(d.get("name", ""), d.get("tags"))
                lines.append(
                    f"  - {d['name']} | region={d.get('region')} | "
                    f"{d.get('vcpus')} vCPU / {memory_gb}GB RAM / {d.get('disk')}GB disk | "
                    f"status={d.get('status')} | tags=[{tags}] | env={env}"
                )

        # Volumes
        if "volume" in by_type:
            lines.append(f"\nVOLUMES ({len(by_type['volume'])} total):")
            for v in by_type["volume"]:
                attached = v.get("attached_to")
                attach_str = f"attached to droplet IDs {attached}" if attached else "UNATTACHED"
                lines.append(
                    f"  - {v['name']} | region={v.get('region')} | "
                    f"{v.get('size_gb')}GB | {attach_str} | status={v.get('status')}"
                )

        # Snapshots
        if "snapshot" in by_type:
            lines.append(f"\nSNAPSHOTS ({len(by_type['snapshot'])} total):")
            for s in by_type["snapshot"]:
                lines.append(
                    f"  - {s['name']} | type={s.get('resource_type')} | "
                    f"{s.get('size_gb')}GB | created={s.get('created_at', 'unknown')}"
                )

        # Databases
        if "database" in by_type:
            lines.append(f"\nMANAGED DATABASES ({len(by_type['database'])} total):")
            for db in by_type["database"]:
                lines.append(
                    f"  - {db['name']} | engine={db.get('engine')}/{db.get('version')} | "
                    f"nodes={db.get('num_nodes')} | region={db.get('region')} | status={db.get('status')}"
                )

        # Load Balancers
        if "load_balancer" in by_type:
            lines.append(f"\nLOAD BALANCERS ({len(by_type['load_balancer'])} total):")
            for lb in by_type["load_balancer"]:
                droplet_ids = lb.get("assigned_droplet_ids", [])
                lines.append(
                    f"  - {lb['name']} | region={lb.get('region')} | "
                    f"assigned_droplets={len(droplet_ids)} | status={lb.get('status')}"
                )

        # Floating IPs
        if "floating_ip" in by_type:
            lines.append(f"\nFLOATING IPs ({len(by_type['floating_ip'])} total):")
            for fip in by_type["floating_ip"]:
                assigned = fip.get("assigned_to")
                assign_str = f"assigned to droplet {assigned}" if assigned else "UNASSIGNED (idle)"
                lines.append(
                    f"  - {fip.get('ip')} | region={fip.get('region')} | {assign_str}"
                )

        lines.append("")
        lines.append("=" * 50)

        if preliminary_findings:
            lines.append("")
            lines.append(f"Rule Engine Preliminary Findings ({len(preliminary_findings)} detected):")
            lines.append("─" * 50)
            for pf in preliminary_findings:
                sev = pf.get("severity", "medium").upper()
                lines.append(
                    f"[{sev}] {pf.get('resource_type', '').upper()}: {pf.get('resource_name')}"
                )
                lines.append(f"  Issue: {pf.get('issue')}")
                lines.append(f"  Recommendation: {pf.get('recommendation')}")
                lines.append(f"  Confidence: {pf.get('confidence', 'medium').upper()}")
                lines.append("")
            lines.append("Instructions:")
            lines.append("1. Include ALL rule-engine findings above in your response — add savings estimates and remediation steps.")
            lines.append("2. Identify ANY ADDITIONAL cost optimization opportunities not already listed.")
            lines.append("3. Do not duplicate findings — each resource issue should appear once.")
        else:
            lines.append("Analyze all resources above for cost optimization opportunities.")

        lines.append("Return your findings as JSON only, following the schema in the system prompt.")

        return "\n".join(lines)

    async def _call_claude(self, user_message: str, model_name: str = CLAUDE_MODEL) -> tuple[str, Dict[str, int]]:
        """Make the API call to Claude and return raw text + token usage."""
        try:
            message = await self.client.messages.create(
                model=model_name,
                max_tokens=MAX_TOKENS,
                system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user_message}],
            )
            usage = message.usage
            cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
            cache_created = getattr(usage, "cache_creation_input_tokens", 0) or 0
            tokens = {
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
            }
            if cache_read or cache_created:
                logger.info(
                    f"Prompt cache: {cache_read} tokens read from cache, "
                    f"{cache_created} tokens written to cache"
                )

            if not message.content:
                raise AIEmptyResponseError("Claude returned an empty response with no content blocks")

            return message.content[0].text, tokens

        except anthropic.AuthenticationError:
            raise AIAuthError("Invalid Claude API key")

        except anthropic.RateLimitError:
            raise AIRateLimitError("Claude API rate limit exceeded")

        except anthropic.APITimeoutError:
            raise AITimeoutError("Claude API request timed out")

        except anthropic.APIStatusError as e:
            raise AIAnalysisError(f"Claude API error {e.status_code}: {e.message}")

        except anthropic.APIConnectionError as e:
            raise AIAnalysisError(f"Claude API connection error: {str(e)}")

    def _parse_response(self, raw: str, total_resources: int) -> Dict[str, Any]:
        """
        Extract and validate JSON from Claude's response.

        Handles cases where Claude wraps output in markdown fences despite instructions.
        Raises AIMalformedResponseError on parse failure — callers must handle this;
        silently returning empty results would hide real failures.
        """
        text = raw.strip()

        if not text:
            raise AIMalformedResponseError("Claude returned an empty text body")

        # Strip markdown code fences if present
        fenced = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
        if fenced:
            text = fenced.group(1).strip()

        try:
            data = json.loads(text)
            return self._validate_and_normalize(data, total_resources)
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.error(f"Failed to parse Claude response as JSON: {exc}\nRaw:\n{raw[:500]}")
            raise AIMalformedResponseError(f"Claude returned malformed JSON: {exc}")

    def _validate_and_normalize(self, data: Dict[str, Any], total_resources: int) -> Dict[str, Any]:
        """Ensure required fields exist and coerce types."""
        summary = data.get("summary", {})
        findings_raw = data.get("findings", [])

        # Normalize summary
        normalized_summary = {
            "total_resources": int(summary.get("total_resources", total_resources)),
            "issues_found": int(summary.get("issues_found", len(findings_raw))),
            "estimated_monthly_savings": str(summary.get("estimated_monthly_savings", "$0")),
            "estimated_annual_savings": str(summary.get("estimated_annual_savings", "$0")),
        }

        # Normalize each finding
        normalized_findings = []
        for f in findings_raw:
            if not isinstance(f, dict):
                continue
            normalized_findings.append({
                "resource_name": str(f.get("resource_name", "unknown")),
                "resource_type": str(f.get("resource_type", "unknown")),
                "severity": str(f.get("severity", "low")).lower(),
                "issue": str(f.get("issue", "")),
                "monthly_savings": str(f.get("monthly_savings", "$0")),
                "annual_savings": str(f.get("annual_savings", "$0")),
                "recommendation": str(f.get("recommendation", "")),
                "remediation_steps": [
                    str(s) for s in f.get("remediation_steps", [])
                ],
            })

        # Re-sync issues_found to actual finding count
        normalized_summary["issues_found"] = len(normalized_findings)

        return {"summary": normalized_summary, "findings": normalized_findings}

