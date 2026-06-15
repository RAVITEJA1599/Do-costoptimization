from pydantic import BaseModel, ConfigDict, Field
from typing import List, Optional, Any
from enum import Enum


class ResourceType(str, Enum):
    DROPLET = "droplet"
    VOLUME = "volume"
    SNAPSHOT = "snapshot"
    DATABASE = "database"
    LOAD_BALANCER = "load_balancer"
    FLOATING_IP = "floating_ip"


class Droplet(BaseModel):
    type: str = ResourceType.DROPLET
    id: str
    name: str
    region: str
    vcpus: int
    memory: int
    disk: int
    status: str
    tags: List[str] = Field(default_factory=list)
    locked: bool = False


class Volume(BaseModel):
    type: str = ResourceType.VOLUME
    id: str
    name: str
    size_gb: int
    region: str
    attached_to: Optional[List[str]] = None
    status: str = "available"


class Snapshot(BaseModel):
    type: str = ResourceType.SNAPSHOT
    id: str
    name: str
    created_at: str
    resource_type: str
    size_gb: int


class ManagedDatabase(BaseModel):
    type: str = ResourceType.DATABASE
    id: str
    name: str
    engine: str
    version: str
    db_name: Optional[str] = None
    num_nodes: int
    region: str
    status: str


class LoadBalancer(BaseModel):
    type: str = ResourceType.LOAD_BALANCER
    id: str
    name: str
    region: str
    assigned_droplet_ids: List[str] = Field(default_factory=list)
    status: str


class FloatingIP(BaseModel):
    type: str = ResourceType.FLOATING_IP
    id: str
    ip: str
    region: str
    assigned_to: Optional[str] = None
    status: str


class ProjectAnalysisRequest(BaseModel):
    project_id: str
    # Optional: pass back the ID issued by POST /api/analyze/reserve so the
    # pre-opened WebSocket receives progress messages.  Any other value is ignored
    # and the server generates a fresh UUID instead.
    reserved_id: Optional[str] = None
    # fast | balanced | deep — maps to a Claude model tier
    analysis_mode: str = "balanced"


# ── AI Analysis models ────────────────────────────────────────────────────────

class AnalysisFinding(BaseModel):
    resource_name: str
    resource_type: str
    severity: str  # "high" | "medium" | "low"
    issue: str
    monthly_savings: str
    annual_savings: str
    recommendation: str
    remediation_steps: List[str] = Field(default_factory=list)


class AnalysisSummary(BaseModel):
    total_resources: int
    issues_found: int
    estimated_monthly_savings: str
    estimated_annual_savings: str


class AIAnalysisResult(BaseModel):
    summary: AnalysisSummary
    findings: List[AnalysisFinding] = Field(default_factory=list)


# ── API response models ───────────────────────────────────────────────────────

class ProjectAnalysisResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    analysis_id: str
    project_id: str
    project_name: str
    resources: List[Any]
    resource_count: dict = Field(default_factory=dict)
    ai_analysis: Optional[AIAnalysisResult] = None
    mock: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    timestamp: str
    model_used: str = ""
    analysis_mode: str = "balanced"
    failure_reason: Optional[str] = None


class ProjectsListResponse(BaseModel):
    projects: List[dict]
    count: int


class AnalysisHistoryItem(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    id: str
    project_id: str
    project_name: str
    resources_scanned: int
    issues_found: int
    estimated_monthly_savings: str
    estimated_annual_savings: str
    status: str
    created_at: str
    run_by: str = ""
    model_used: str = ""
    analysis_mode: str = "balanced"
    failure_reason: Optional[str] = None


class HistoryListResponse(BaseModel):
    analyses: List[AnalysisHistoryItem]
    count: int


class UserItem(BaseModel):
    id: str
    email: str
    created_at: str


class UsersListResponse(BaseModel):
    users: List[UserItem]
    count: int


class ErrorResponse(BaseModel):
    error: str
    status_code: int = 400
    details: Optional[str] = None


# ── Monitoring coverage models ─────────────────────────────────────────────────

class MonitoringDropletItem(BaseModel):
    droplet_id: str
    droplet_name: str
    monitoring_status: str  # "enabled" | "missing" | "unknown"


class MonitoringCoverageResponse(BaseModel):
    total_droplets: int
    monitoring_enabled: int
    monitoring_missing: int
    monitoring_unknown: int
    droplets: List[MonitoringDropletItem]
