"""
Tests for rule_engine.py — environment detection and all rule logic.

Run from the backend/ directory:
    pytest tests/test_rule_engine.py -v
"""
import sys
import os

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from rule_engine import RuleEngine, _detect_effective_environment  # noqa: E402


# ── Fixtures ───────────────────────────────────────────────────────────────────

def _droplet(name, vcpus=4, memory=8192, status="active", tags=None) -> dict:
    return {
        "type": "droplet",
        "id": "1",
        "name": name,
        "vcpus": vcpus,
        "memory": memory,
        "disk": 80,
        "status": status,
        "tags": tags or [],
    }


def _db(name, num_nodes=1, engine="pg", version="15", tags=None) -> dict:
    return {
        "type": "database",
        "id": "1",
        "name": name,
        "engine": engine,
        "version": version,
        "num_nodes": num_nodes,
        "region": "nyc3",
        "status": "online",
        "tags": tags or [],
    }


# ── _detect_effective_environment ─────────────────────────────────────────────

class TestDetectEffectiveEnvironment:

    # Tag-based detection
    def test_production_tag(self):
        assert _detect_effective_environment("my-droplet", ["production"]) == "PROD"

    def test_prod_tag(self):
        assert _detect_effective_environment("my-droplet", ["prod"]) == "PROD"

    def test_dev_tag(self):
        assert _detect_effective_environment("my-droplet", ["dev"]) == "DEV"

    def test_staging_tag(self):
        assert _detect_effective_environment("my-droplet", ["staging"]) == "STAGING"

    def test_uat_tag(self):
        assert _detect_effective_environment("my-droplet", ["uat"]) == "UAT"

    def test_demo_tag(self):
        assert _detect_effective_environment("my-droplet", ["demo"]) == "DEMO"

    def test_test_tag(self):
        assert _detect_effective_environment("my-droplet", ["test"]) == "TEST"

    def test_dr_tag(self):
        assert _detect_effective_environment("my-droplet", ["dr"]) == "DR"

    def test_backup_tag(self):
        assert _detect_effective_environment("my-droplet", ["backup"]) == "BACKUP"

    def test_poc_tag(self):
        assert _detect_effective_environment("my-droplet", ["poc"]) == "POC"

    def test_tag_is_case_insensitive(self):
        assert _detect_effective_environment("any-name", ["PRODUCTION"]) == "PROD"
        assert _detect_effective_environment("any-name", ["Production"]) == "PROD"

    def test_tag_takes_precedence_over_name(self):
        """Explicit prod tag wins even when the name says DEV."""
        assert _detect_effective_environment("SD-Widget-DEV", ["prod"]) == "PROD"

    # Name-based detection — examples from user specification
    def test_prod_from_name_dash(self):
        assert _detect_effective_environment("SD-Dms-PROD") == "PROD"

    def test_dev_from_name_dash(self):
        assert _detect_effective_environment("SD-Crm-DEV") == "DEV"

    def test_qa_from_name_dash(self):
        assert _detect_effective_environment("SD-Mozart2.0-QA") == "QA"

    def test_demo_from_name_dash(self):
        assert _detect_effective_environment("SD-Mozart-DEMO") == "DEMO"

    def test_demo_from_name_mixed_case(self):
        assert _detect_effective_environment("Customer-Demo-App") == "DEMO"

    def test_uat_from_name_prefix(self):
        assert _detect_effective_environment("uat-web") == "UAT"

    def test_test_from_name_prefix(self):
        assert _detect_effective_environment("test-server") == "TEST"

    def test_dr_from_name_prefix(self):
        assert _detect_effective_environment("dr-database") == "DR"

    def test_backup_from_name_prefix(self):
        assert _detect_effective_environment("backup-node") == "BACKUP"

    def test_staging_from_stg_segment(self):
        assert _detect_effective_environment("backend-stg") == "STAGING"

    def test_staging_from_stage_segment(self):
        assert _detect_effective_environment("api-stage-01") == "STAGING"

    def test_poc_from_name(self):
        assert _detect_effective_environment("sd-poc-experiment") == "POC"

    def test_underscore_separator(self):
        assert _detect_effective_environment("web_server_prod") == "PROD"

    def test_dot_separator(self):
        assert _detect_effective_environment("api.service.dev") == "DEV"

    def test_case_insensitive_name_segment(self):
        assert _detect_effective_environment("sd-rabbitmq-PROD") == "PROD"
        assert _detect_effective_environment("sd-rabbitmq-prod") == "PROD"

    def test_unknown_when_no_match(self):
        assert _detect_effective_environment("SD-ATHENA-BK") == "UNKNOWN"

    def test_unknown_empty_name_no_tags(self):
        assert _detect_effective_environment("") == "UNKNOWN"

    def test_unknown_no_tags_no_env_segment(self):
        assert _detect_effective_environment("web-server-01", []) == "UNKNOWN"

    def test_unrelated_tags_fall_through_to_name(self):
        assert _detect_effective_environment("SD-API-QA", ["web", "nginx"]) == "QA"


# ── _rule_over_provisioned_droplets ───────────────────────────────────────────

class TestOverProvisionedDroplets:
    """
    Large droplets (≥8 vCPU or ≥16 GB RAM) in PROD or DR are suppressed.
    All other environments still receive the finding.
    """
    LARGE_VCPU = {"vcpus": 8, "memory": 8192}
    LARGE_MEM  = {"vcpus": 4, "memory": 16384}
    LARGE_BOTH = {"vcpus": 16, "memory": 32768}
    SMALL      = {"vcpus": 2, "memory": 4096}

    def _run(self, droplets):
        return RuleEngine()._rule_over_provisioned_droplets(droplets)

    # --- False positives that must be suppressed ---

    def test_prod_from_name_no_finding(self):
        """SD-Dms-PROD with 8 vCPU must NOT generate a finding (the reported false positive)."""
        assert self._run([_droplet("SD-Dms-PROD", vcpus=8, memory=8192)]) == []

    def test_prod_from_tag_no_finding(self):
        assert self._run([_droplet("my-droplet", vcpus=8, tags=["production"])]) == []

    def test_prod_large_mem_no_finding(self):
        assert self._run([_droplet("web-prod", **self.LARGE_MEM)]) == []

    def test_prod_large_both_no_finding(self):
        assert self._run([_droplet("SD-API-PROD", **self.LARGE_BOTH)]) == []

    def test_dr_from_name_no_finding(self):
        """DR mirrors production size — must not be flagged."""
        assert self._run([_droplet("dr-database-01", **self.LARGE_VCPU)]) == []

    def test_dr_from_tag_no_finding(self):
        assert self._run([_droplet("any-name", vcpus=16, tags=["dr"])]) == []

    # --- Findings that must still be emitted ---

    def test_dev_large_generates_finding(self):
        findings = self._run([_droplet("SD-Crm-DEV", **self.LARGE_VCPU)])
        assert len(findings) == 1
        assert findings[0]["resource_name"] == "SD-Crm-DEV"
        assert findings[0]["severity"] == "medium"

    def test_staging_large_generates_finding(self):
        findings = self._run([_droplet("api-staging", **self.LARGE_VCPU)])
        assert len(findings) == 1

    def test_qa_large_generates_finding(self):
        findings = self._run([_droplet("SD-Mozart2.0-QA", **self.LARGE_VCPU)])
        assert len(findings) == 1

    def test_uat_large_generates_finding(self):
        findings = self._run([_droplet("uat-web-01", **self.LARGE_VCPU)])
        assert len(findings) == 1

    def test_demo_large_generates_finding(self):
        findings = self._run([_droplet("Customer-Demo-App", **self.LARGE_VCPU)])
        assert len(findings) == 1

    def test_test_large_generates_finding(self):
        findings = self._run([_droplet("test-server", **self.LARGE_VCPU)])
        assert len(findings) == 1

    def test_poc_large_generates_finding(self):
        findings = self._run([_droplet("poc-experiment", **self.LARGE_VCPU)])
        assert len(findings) == 1

    def test_backup_large_generates_finding(self):
        findings = self._run([_droplet("backup-node", **self.LARGE_VCPU)])
        assert len(findings) == 1

    def test_unknown_large_generates_finding(self):
        """UNKNOWN environment — still flagged, as we cannot confirm it is production."""
        findings = self._run([_droplet("SD-ATHENA-BK", **self.LARGE_VCPU)])
        assert len(findings) == 1

    def test_small_droplet_no_finding_regardless_of_env(self):
        """Small droplets must never be flagged, even in unknown environments."""
        for name in ("SD-App-PROD", "web-dev", "unknown-host"):
            assert self._run([_droplet(name, **self.SMALL)]) == []

    def test_mixed_prod_and_dev_only_dev_flagged(self):
        droplets = [
            _droplet("SD-Api-PROD", **self.LARGE_VCPU),
            _droplet("SD-Api-DEV",  **self.LARGE_VCPU),
            _droplet("SD-Api-QA",   **self.LARGE_VCPU),
        ]
        findings = self._run(droplets)
        names = {f["resource_name"] for f in findings}
        assert "SD-Api-PROD" not in names
        assert "SD-Api-DEV" in names
        assert "SD-Api-QA" in names

    def test_finding_content_for_large_vcpu(self):
        findings = self._run([_droplet("web-dev", vcpus=8, memory=8192)])
        assert len(findings) == 1
        f = findings[0]
        assert "8" in f["issue"]
        assert f["confidence"] == "low"
        assert "downsize" in f["recommendation"]

    def test_finding_content_for_large_memory(self):
        findings = self._run([_droplet("web-dev", vcpus=4, memory=32768)])
        assert len(findings) == 1
        f = findings[0]
        assert "32.0" in f["issue"]  # mem_gb computed from 32768/1024

    def test_exactly_8_vcpu_triggers(self):
        assert len(self._run([_droplet("dev-host", vcpus=8, memory=4096)])) == 1

    def test_exactly_16384_mb_triggers(self):
        assert len(self._run([_droplet("dev-host", vcpus=2, memory=16384)])) == 1

    def test_7_vcpu_below_threshold_no_finding(self):
        assert self._run([_droplet("dev-host", vcpus=7, memory=8192)]) == []

    def test_16383_mb_below_threshold_no_finding(self):
        assert self._run([_droplet("dev-host", vcpus=4, memory=16383)]) == []


# ── _rule_large_databases ─────────────────────────────────────────────────────

class TestLargeDatabases:
    """
    Database clusters with ≥3 nodes are only flagged for non-production environments.
    PROD and DR clusters are expected to use HA — no finding emitted.
    """

    def _run(self, databases):
        return RuleEngine()._rule_large_databases(databases)

    # --- Suppressed for production-like environments ---

    def test_prod_db_name_no_finding(self):
        assert self._run([_db("sd-postgres-prod", num_nodes=3)]) == []

    def test_prod_db_many_nodes_no_finding(self):
        assert self._run([_db("sd-postgres-prod", num_nodes=5)]) == []

    def test_dr_db_no_finding(self):
        assert self._run([_db("dr-database-cluster", num_nodes=3)]) == []

    # --- Finding emitted for non-production environments ---

    def test_dev_db_large_generates_finding(self):
        findings = self._run([_db("sd-postgres-dev", num_nodes=3)])
        assert len(findings) == 1
        assert findings[0]["resource_name"] == "sd-postgres-dev"

    def test_staging_db_large_generates_finding(self):
        assert len(self._run([_db("db-staging", num_nodes=3)])) == 1

    def test_unknown_db_large_generates_finding(self):
        """UNKNOWN environment — still flagged."""
        assert len(self._run([_db("my-postgres-cluster", num_nodes=3)])) == 1

    def test_small_db_no_finding(self):
        """Clusters with fewer than 3 nodes are never flagged."""
        for name in ("sd-db-prod", "sd-db-dev", "sd-db-unknown"):
            assert self._run([_db(name, num_nodes=2)]) == []

    def test_single_node_no_finding(self):
        assert self._run([_db("sd-postgres-dev", num_nodes=1)]) == []

    def test_exactly_3_nodes_triggers(self):
        assert len(self._run([_db("sd-postgres-dev", num_nodes=3)])) == 1

    def test_finding_content(self):
        findings = self._run([_db("sd-postgres-dev", num_nodes=3, engine="pg", version="15")])
        f = findings[0]
        assert "3" in f["issue"]
        assert "pg" in f["issue"]
        assert f["severity"] == "medium"
        assert f["confidence"] == "medium"


# ── _rule_powered_off_droplets — fires regardless of environment ──────────────

class TestPoweredOffDroplets:

    def _run(self, droplets):
        return RuleEngine()._rule_powered_off_droplets(droplets)

    def test_prod_powered_off_generates_finding(self):
        """Even PROD droplets being off costs money — must always be flagged."""
        findings = self._run([_droplet("SD-Api-PROD", status="off")])
        assert len(findings) == 1
        assert findings[0]["severity"] == "high"

    def test_dr_powered_off_generates_finding(self):
        findings = self._run([_droplet("dr-server", status="off")])
        assert len(findings) == 1

    def test_dev_powered_off_generates_finding(self):
        assert len(self._run([_droplet("dev-host", status="off")])) == 1

    def test_active_droplet_no_finding(self):
        assert self._run([_droplet("SD-Api-PROD", status="active")]) == []

    def test_unknown_env_powered_off_generates_finding(self):
        assert len(self._run([_droplet("SD-ATHENA-BK", status="off")])) == 1


# ── Other rules — unaffected by environment detection ─────────────────────────

class TestOtherRulesUnaffected:

    def test_unattached_volume_fires_regardless_of_name(self):
        v = {"name": "vol-prod-01", "size_gb": 100, "attached_to": None}
        findings = RuleEngine()._rule_unattached_volumes([v])
        assert len(findings) == 1

    def test_attached_volume_no_finding(self):
        v = {"name": "vol-dev-01", "size_gb": 50, "attached_to": ["droplet-1"]}
        assert RuleEngine()._rule_unattached_volumes([v]) == []

    def test_unassigned_floating_ip_fires(self):
        fip = {"ip": "1.2.3.4", "assigned_to": None}
        assert len(RuleEngine()._rule_unassigned_floating_ips([fip])) == 1

    def test_idle_load_balancer_fires(self):
        lb = {"name": "lb-prod", "assigned_droplet_ids": []}
        assert len(RuleEngine()._rule_idle_load_balancers([lb])) == 1


# ── run() integration ─────────────────────────────────────────────────────────

class TestRunIntegration:

    def test_prod_large_droplet_not_in_findings(self):
        """End-to-end: SD-Dms-PROD with 8 vCPU must produce zero findings."""
        resources = [_droplet("SD-Dms-PROD", vcpus=8, memory=8192)]
        result = RuleEngine().run(resources, {"total": 1})
        assert result["findings"] == []
        assert result["summary"]["preliminary_findings"] == 0

    def test_dev_large_droplet_in_findings(self):
        resources = [_droplet("SD-Dms-DEV", vcpus=8, memory=8192)]
        result = RuleEngine().run(resources, {"total": 1})
        assert len(result["findings"]) == 1

    def test_prod_db_ha_not_in_findings(self):
        resources = [_db("sd-postgres-prod", num_nodes=3)]
        result = RuleEngine().run(resources, {"total": 1})
        assert result["findings"] == []

    def test_mixed_fleet_correct_findings(self):
        """Mixed fleet: only DEV large droplet and DEV 3-node DB should be flagged."""
        resources = [
            _droplet("SD-Api-PROD",    vcpus=16, memory=32768),   # suppressed (PROD)
            _droplet("SD-Api-DEV",     vcpus=8,  memory=8192),    # flagged (DEV)
            _droplet("SD-Api-STAGING", vcpus=4,  memory=4096),    # small — no finding
            _db("db-prod",   num_nodes=3),                        # suppressed (PROD)
            _db("db-dev",    num_nodes=3),                        # flagged (DEV)
            _db("db-single", num_nodes=1),                        # below threshold
        ]
        result = RuleEngine().run(resources, {"total": len(resources)})
        names = {f["resource_name"] for f in result["findings"]}
        assert "SD-Api-PROD" not in names
        assert "db-prod" not in names
        assert "SD-Api-DEV" in names
        assert "db-dev" in names
        assert result["summary"]["preliminary_findings"] == 2
