"""
Tests for monitoring-related rule engine behavior and MockAnalyzer integration.

Covers:
  - Rule engine _rule_no_monitoring: missing → finding, enabled/unknown → no finding
  - Recommendation text: correct install command, no wrong doctl command
  - MockAnalyzer: preliminary_findings monitoring entries are included in output
  - MockAnalyzer: non-monitoring preliminary_findings are not passed through

Run from the backend/ directory:
    pytest tests/test_rule_engine_monitoring.py -v
"""
import sys
import os

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from rule_engine import RuleEngine          # noqa: E402
from mock_analyzer import MockAnalyzer      # noqa: E402


# ── Helpers ────────────────────────────────────────────────────────────────────

def _mon(droplet_name: str, status: str) -> dict:
    return {"droplet_id": "1", "droplet_name": droplet_name, "monitoring_status": status}


MONITORING_FINDING = {
    "resource_name": "web-01",
    "resource_type": "droplet",
    "severity": "high",
    "issue": (
        "DigitalOcean Monitoring Agent not enabled — CPU, memory, and disk metrics "
        "are unavailable; alerts cannot be configured for this Droplet"
    ),
    "recommendation": (
        "Install the DigitalOcean Monitoring Agent via SSH: "
        "curl -sSL https://repos.sonar.digitalocean.com/install.sh | sudo bash. "
        "See: https://docs.digitalocean.com/products/monitoring/quickstart/"
    ),
    "confidence": "high",
}


# ── Rule engine: _rule_no_monitoring ──────────────────────────────────────────

class TestRuleNoMonitoring:

    def test_missing_generates_high_severity_finding(self):
        findings = RuleEngine()._rule_no_monitoring([_mon("web-01", "missing")])
        assert len(findings) == 1
        f = findings[0]
        assert f["severity"] == "high"
        assert f["resource_name"] == "web-01"
        assert f["resource_type"] == "droplet"
        assert f["confidence"] == "high"

    def test_enabled_generates_no_finding(self):
        assert RuleEngine()._rule_no_monitoring([_mon("web-01", "enabled")]) == []

    def test_unknown_generates_no_finding(self):
        """'unknown' status (rate-limit, timeout) must not be flagged as missing."""
        assert RuleEngine()._rule_no_monitoring([_mon("web-01", "unknown")]) == []

    def test_mixed_statuses_only_flags_missing(self):
        data = [
            _mon("a", "missing"),
            _mon("b", "enabled"),
            _mon("c", "unknown"),
            _mon("d", "missing"),
        ]
        findings = RuleEngine()._rule_no_monitoring(data)
        assert len(findings) == 2
        names = {f["resource_name"] for f in findings}
        assert names == {"a", "d"}

    def test_recommendation_contains_correct_install_command(self):
        finding = RuleEngine()._rule_no_monitoring([_mon("x", "missing")])[0]
        rec = finding["recommendation"]
        assert "curl -sSL" in rec
        assert "repos.sonar.digitalocean.com" in rec

    def test_recommendation_does_not_contain_wrong_doctl_command(self):
        finding = RuleEngine()._rule_no_monitoring([_mon("x", "missing")])[0]
        assert "enable-private-networking" not in finding["recommendation"]

    def test_run_integrates_monitoring_findings(self):
        monitoring_data = [_mon("web-01", "missing"), _mon("db-01", "enabled")]
        result = RuleEngine().run([], {"total": 0}, monitoring_data=monitoring_data)
        monitoring_findings = [
            f for f in result["findings"]
            if "Monitoring Agent" in f.get("issue", "")
        ]
        assert len(monitoring_findings) == 1
        assert monitoring_findings[0]["resource_name"] == "web-01"

    def test_run_does_not_flag_unknown_status(self):
        monitoring_data = [_mon("web-01", "unknown"), _mon("db-01", "unknown")]
        result = RuleEngine().run([], {"total": 0}, monitoring_data=monitoring_data)
        assert len(result["findings"]) == 0


# ── MockAnalyzer: preliminary_findings integration ────────────────────────────

class TestMockAnalyzerMonitoring:

    @pytest.mark.asyncio
    async def test_monitoring_finding_included_when_preliminary_findings_present(self):
        result = await MockAnalyzer().analyze(
            project_name="test",
            resources=[],
            resource_count={"total": 0},
            preliminary_findings=[MONITORING_FINDING],
        )
        monitoring = [
            f for f in result["findings"]
            if "Monitoring Agent" in f.get("issue", "")
        ]
        assert len(monitoring) == 1
        assert monitoring[0]["resource_name"] == "web-01"
        assert monitoring[0]["severity"] == "high"

    @pytest.mark.asyncio
    async def test_monitoring_finding_has_all_required_fields(self):
        result = await MockAnalyzer().analyze(
            project_name="test",
            resources=[],
            resource_count={"total": 0},
            preliminary_findings=[MONITORING_FINDING],
        )
        f = next(f for f in result["findings"] if "Monitoring Agent" in f.get("issue", ""))
        for field in ("resource_name", "resource_type", "severity", "issue",
                      "monthly_savings", "annual_savings", "recommendation", "remediation_steps"):
            assert field in f, f"Missing field: {field}"
        assert isinstance(f["remediation_steps"], list)
        assert len(f["remediation_steps"]) > 0

    @pytest.mark.asyncio
    async def test_monitoring_finding_remediation_has_correct_install_command(self):
        result = await MockAnalyzer().analyze(
            project_name="test",
            resources=[],
            resource_count={"total": 0},
            preliminary_findings=[MONITORING_FINDING],
        )
        f = next(f for f in result["findings"] if "Monitoring Agent" in f.get("issue", ""))
        steps_text = " ".join(f["remediation_steps"])
        assert "curl -sSL" in steps_text
        assert "repos.sonar.digitalocean.com" in steps_text

    @pytest.mark.asyncio
    async def test_no_monitoring_finding_without_preliminary_findings(self):
        result = await MockAnalyzer().analyze(
            project_name="test",
            resources=[],
            resource_count={"total": 0},
            preliminary_findings=None,
        )
        monitoring = [f for f in result["findings"] if "Monitoring Agent" in f.get("issue", "")]
        assert len(monitoring) == 0

    @pytest.mark.asyncio
    async def test_no_monitoring_finding_with_empty_preliminary_findings(self):
        result = await MockAnalyzer().analyze(
            project_name="test",
            resources=[],
            resource_count={"total": 0},
            preliminary_findings=[],
        )
        monitoring = [f for f in result["findings"] if "Monitoring Agent" in f.get("issue", "")]
        assert len(monitoring) == 0

    @pytest.mark.asyncio
    async def test_non_monitoring_preliminary_findings_not_passed_through(self):
        """Rule engine findings for volumes/IPs must not leak into MockAnalyzer output."""
        non_monitoring = {
            "resource_name": "vol-01",
            "resource_type": "volume",
            "severity": "high",
            "issue": "Unattached volume (50 GB)",
            "recommendation": "Delete or attach the volume",
            "confidence": "high",
        }
        result = await MockAnalyzer().analyze(
            project_name="test",
            resources=[],
            resource_count={"total": 0},
            preliminary_findings=[non_monitoring],
        )
        assert len(result["findings"]) == 0

    @pytest.mark.asyncio
    async def test_multiple_monitoring_findings_all_included(self):
        pf2 = dict(MONITORING_FINDING, resource_name="db-01")
        result = await MockAnalyzer().analyze(
            project_name="test",
            resources=[],
            resource_count={"total": 0},
            preliminary_findings=[MONITORING_FINDING, pf2],
        )
        monitoring = [f for f in result["findings"] if "Monitoring Agent" in f.get("issue", "")]
        assert len(monitoring) == 2
        names = {f["resource_name"] for f in monitoring}
        assert names == {"web-01", "db-01"}

    @pytest.mark.asyncio
    async def test_savings_zero_for_monitoring_findings(self):
        """Monitoring findings have $0 savings (operational risk, not direct cost)."""
        result = await MockAnalyzer().analyze(
            project_name="test",
            resources=[],
            resource_count={"total": 0},
            preliminary_findings=[MONITORING_FINDING],
        )
        f = next(f for f in result["findings"] if "Monitoring Agent" in f.get("issue", ""))
        assert f["monthly_savings"] == "$0"
        assert f["annual_savings"] == "$0"
