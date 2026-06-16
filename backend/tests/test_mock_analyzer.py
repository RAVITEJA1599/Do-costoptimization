"""
Tests for MockAnalyzer._oversized_droplets environment-aware suppression.

Verifies that PROD and DR environments are never flagged as over-provisioned,
regardless of whether the environment is detected from a tag or the name.
"""

import pytest
from mock_analyzer import MockAnalyzer


def _droplet(name, vcpus=4, memory=8192, status="active", tags=None, did="d-1"):
    return {
        "id": did,
        "name": name,
        "vcpus": vcpus,
        "memory": memory,
        "disk": 80,
        "status": status,
        "tags": tags or [],
        "type": "droplet",
    }


def _run(droplets):
    return MockAnalyzer()._oversized_droplets(droplets)


# ── PROD suppression (name-based) ─────────────────────────────────────────────

class TestProdNameSuppression:
    def test_sd_n8n_prod_no_finding(self):
        """SD-N8N-PROD (4 vCPU, no tags) must NOT generate a finding."""
        assert _run([_droplet("SD-N8N-PROD", vcpus=4, memory=16384)]) == []

    def test_sd_dms_prod_no_finding(self):
        """SD-Dms-PROD (8 vCPU, no tags) must NOT generate a finding."""
        assert _run([_droplet("SD-Dms-PROD", vcpus=8, memory=8192)]) == []

    def test_prod_large_no_finding(self):
        """Any PROD droplet with ≥8 vCPUs must NOT generate a finding."""
        assert _run([_droplet("APP-PROD", vcpus=16, memory=32768)]) == []

    def test_prod_underscore_separator(self):
        """Name using underscore separator (SD_PROD_API) must be detected as PROD."""
        assert _run([_droplet("SD_PROD_API", vcpus=8, memory=8192)]) == []


# ── DR suppression (name-based) ───────────────────────────────────────────────

class TestDrNameSuppression:
    def test_dr_database_no_finding(self):
        """dr-database-01 (4 vCPU) must NOT generate a finding — DR is production-like."""
        assert _run([_droplet("dr-database-01", vcpus=4, memory=8192)]) == []

    def test_dr_large_no_finding(self):
        """dr-replica-01 (8 vCPU) must NOT generate a finding."""
        assert _run([_droplet("dr-replica-01", vcpus=8, memory=16384)]) == []


# ── Tag-based PROD suppression ────────────────────────────────────────────────

class TestProdTagSuppression:
    def test_prod_tag_4vcpu_no_finding(self):
        """Droplet with explicit 'prod' tag and 4 vCPUs must not be flagged."""
        assert _run([_droplet("some-service", vcpus=4, tags=["prod"])]) == []

    def test_production_tag_8vcpu_no_finding(self):
        """Droplet with 'production' tag and 8 vCPUs must not be flagged."""
        assert _run([_droplet("some-service", vcpus=8, tags=["production"])]) == []


# ── Non-production environments should still be flagged ───────────────────────

class TestNonProdFindings:
    def test_sd_crm_dev_8vcpu_generates_finding(self):
        """SD-Crm-DEV with 8 vCPUs should generate a finding (DEV is not PROD-like)."""
        findings = _run([_droplet("SD-Crm-DEV", vcpus=8, memory=8192)])
        assert len(findings) == 1
        assert findings[0]["resource_name"] == "SD-Crm-DEV"
        assert findings[0]["severity"] == "medium"

    def test_sd_crm_dev_4vcpu_generates_finding(self):
        """SD-Crm-DEV with 4 vCPUs should generate a finding."""
        findings = _run([_droplet("SD-Crm-DEV", vcpus=4, memory=8192)])
        assert len(findings) == 1
        assert findings[0]["resource_name"] == "SD-Crm-DEV"
        assert findings[0]["severity"] == "low"

    def test_op_demo_generates_finding(self):
        """OP-DEMO (4 vCPU) should generate a finding — DEMO is not PROD-like."""
        findings = _run([_droplet("OP-DEMO", vcpus=4, memory=8192)])
        assert len(findings) == 1
        assert findings[0]["resource_name"] == "OP-DEMO"

    def test_unknown_environment_generates_finding(self):
        """Droplet with no env in tags or name should still be flagged."""
        findings = _run([_droplet("my-service-01", vcpus=4, memory=8192)])
        assert len(findings) == 1

    def test_staging_generates_finding(self):
        """STAGING environment should still be flagged as potentially over-provisioned."""
        findings = _run([_droplet("SD-App-STAGING", vcpus=8, memory=8192)])
        assert len(findings) == 1

    def test_qa_generates_finding(self):
        findings = _run([_droplet("api-qa", vcpus=4, memory=8192)])
        assert len(findings) == 1


# ── Edge cases ────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_inactive_droplet_skipped(self):
        """Powered-off droplets are handled by _inactive_droplets, not this rule."""
        assert _run([_droplet("SD-N8N-DEV", vcpus=8, status="off")]) == []

    def test_small_droplet_not_flagged(self):
        """Droplets with fewer than 4 vCPUs are never flagged as oversized."""
        assert _run([_droplet("tiny-dev", vcpus=2, memory=2048)]) == []

    def test_tag_takes_precedence_over_name(self):
        """A 'dev' tag on a droplet named PROD-service sets env=DEV (tag wins)."""
        findings = _run([_droplet("PROD-service", vcpus=8, tags=["dev"])])
        assert len(findings) == 1  # dev tag wins → not suppressed

    def test_multiple_droplets_mixed(self):
        """Mixed pool: PROD suppressed, DEV flagged."""
        droplets = [
            _droplet("SD-API-PROD", vcpus=8, did="d-1"),
            _droplet("SD-API-DEV", vcpus=8, did="d-2"),
        ]
        findings = _run(droplets)
        assert len(findings) == 1
        assert findings[0]["resource_name"] == "SD-API-DEV"
