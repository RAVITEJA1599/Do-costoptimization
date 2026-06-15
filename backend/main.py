import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from monitoring_scanner import MonitoringScanner
from ai_analyzer import (
    AIAnalyzer, AIAnalysisError, AIAuthError, AIRateLimitError,
    AITimeoutError, AIMalformedResponseError,
)
from mock_analyzer import MockAnalyzer
from rule_engine import RuleEngine
import auth as auth_module
from auth import get_current_user, verify_token
from config import config
from rate_limiter import limiter, rate_limit_error_handler
from db import (
    close_db, create_analysis, get_analyses, get_analysis_by_id,
    init_db, update_analysis,
)
from digitalocean_scanner import (
    DigitalOceanAPIError,
    DigitalOceanScanner,
    InvalidTokenError,
    ProjectNotFoundError,
    RateLimitError,
)
from models import (
    AIAnalysisResult,
    AnalysisHistoryItem,
    HistoryListResponse,
    MonitoringCoverageResponse,
    MonitoringDropletItem,
    ProjectAnalysisRequest,
    ProjectAnalysisResponse,
    ProjectsListResponse,
    UsersListResponse,
    UserItem,
)
from websocket_manager import ws_manager

MODEL_MAPPING: dict = {
    "fast":     "claude-haiku-4-5-20251001",
    "balanced": "claude-sonnet-4-20250514",
    "deep":     "claude-opus-4-5",
}
VALID_MODES = set(MODEL_MAPPING)

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=config.LOG_LEVEL,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


# ── Application lifespan ──────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up...")
    config.validate()  # Abort immediately if required env vars (incl. JWT_SECRET) are missing
    await init_db(config.DATABASE_URL)
    logger.info("Backend ready")
    yield
    logger.info("Shutting down...")
    await close_db()


app = FastAPI(
    title="DigitalOcean AI Cost Detective",
    description="Backend API for analyzing DigitalOcean cloud costs",
    version="1.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_error_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register auth router (public — /api/auth/signup, /api/auth/login)
app.include_router(auth_module.router)


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health_check():
    return {"status": "healthy"}


# ── Projects ──────────────────────────────────────────────────────────────────

@app.get("/api/projects", response_model=ProjectsListResponse)
async def get_projects(current_user: dict = Depends(get_current_user)):
    """Fetch all available DigitalOcean Projects."""
    if not config.DIGITALOCEAN_TOKEN:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="DigitalOcean token not configured")
    try:
        async with DigitalOceanScanner(config.DIGITALOCEAN_TOKEN) as scanner:
            projects = await scanner.get_projects()
        logger.info(f"Fetched {len(projects)} projects")
        return ProjectsListResponse(projects=projects, count=len(projects))

    except InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid DigitalOcean API Token")
    except RateLimitError:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            detail="DigitalOcean API rate limit exceeded")
    except DigitalOceanAPIError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    except Exception as exc:
        logger.error(f"Unexpected error fetching projects: {exc}", exc_info=True)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="Internal server error")


# ── Monitoring Coverage ───────────────────────────────────────────────────────

@app.get("/api/monitoring-coverage", response_model=MonitoringCoverageResponse)
async def get_monitoring_coverage(
    project_id: Optional[str] = Query(default=None),
    current_user: dict = Depends(get_current_user),
):
    """
    Scan Droplets for monitoring agent coverage.

    Optionally filter to a single project via ?project_id=<id>.  If omitted,
    all Droplets in the account are scanned.

    Returns summary counts and a per-Droplet monitoring status list.
    The scan uses the DigitalOcean Monitoring API (CPU metrics endpoint with a
    6-hour window): a non-empty result means the agent is installed and reporting.
    """
    if not config.DIGITALOCEAN_TOKEN:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="DigitalOcean token not configured",
        )

    try:
        async with DigitalOceanScanner(config.DIGITALOCEAN_TOKEN) as scanner:
            droplets = await scanner.get_droplets(project_id or "")
    except InvalidTokenError:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="Invalid DigitalOcean API Token",
        )
    except RateLimitError:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="DigitalOcean API rate limit exceeded",
        )
    except DigitalOceanAPIError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    except Exception as exc:
        logger.error(f"Failed to fetch Droplets for monitoring scan: {exc}", exc_info=True)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch Droplets",
        )

    if not droplets:
        return MonitoringCoverageResponse(
            total_droplets=0,
            monitoring_enabled=0,
            monitoring_missing=0,
            monitoring_unknown=0,
            droplets=[],
        )

    droplet_dicts = [d.dict() for d in droplets]
    try:
        results = await MonitoringScanner(config.DIGITALOCEAN_TOKEN).scan_all_droplets_monitoring(
            droplet_dicts
        )
    except ValueError as exc:
        # Invalid DO token detected by the monitoring API —  502 not 401 so the
        # frontend's session-expiry interceptor (which acts on 401) is not triggered.
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    except Exception as exc:
        logger.error(f"Monitoring coverage scan failed: {exc}", exc_info=True)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail="Monitoring coverage scan failed",
        )

    enabled = sum(1 for d in results if d["monitoring_status"] == "enabled")
    missing = sum(1 for d in results if d["monitoring_status"] == "missing")
    unknown = sum(1 for d in results if d["monitoring_status"] == "unknown")

    return MonitoringCoverageResponse(
        total_droplets=len(results),
        monitoring_enabled=enabled,
        monitoring_missing=missing,
        monitoring_unknown=unknown,
        droplets=[MonitoringDropletItem(**d) for d in results],
    )


# ── Analysis ID reservation ───────────────────────────────────────────────────

@app.post("/api/analyze/reserve")
async def reserve_analysis_id(current_user: dict = Depends(get_current_user)):
    """
    Issue a server-generated analysis ID so the client can open the WebSocket
    before calling POST /api/analyze.

    Creates a placeholder pending row in the DB.  POST /api/analyze validates
    this ID is server-issued before using it; any other value is ignored.
    """
    analysis_id = str(uuid.uuid4())
    user_id = current_user.get("user_id")
    user_email = current_user.get("email")
    await create_analysis(
        analysis_id,
        project_id="__reserved__",
        user_id=user_id,
        user_email=user_email,
    )
    return {"analysis_id": analysis_id}


# ── Analyze ───────────────────────────────────────────────────────────────────

@app.post("/api/analyze", response_model=ProjectAnalysisResponse)
async def analyze_project(
    request: ProjectAnalysisRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Full analysis pipeline:

      Stage 1  — Connecting to DigitalOcean
      Stage 2  — Loading Project Information
      Stage 3  — Fetching Resources
      Stage 4  — Collecting Droplets
      Stage 5  — Collecting Volumes
      Stage 6  — Collecting Snapshots
      Stage 7  — Collecting Databases
      Stage 8  — Collecting Load Balancers
      Stage 9  — Running Rule Engine
      Stage 10 — Analyzing Infrastructure with Claude
      Stage 11 — Generating Recommendations
      Stage 12 — Storing Results
      Stage 13 — Analysis Complete

    Call POST /api/analyze/reserve first to obtain a server-generated analysis_id,
    open the WebSocket at /ws/progress/{analysis_id}, then call this endpoint with
    reserved_id set to the server-issued value to receive live progress messages.
    """
    # ── Pre-flight checks ──────────────────────────────────────────────────────
    if not config.DIGITALOCEAN_TOKEN:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="DigitalOcean token not configured")

    # Validate analysis_mode
    analysis_mode = request.analysis_mode if request.analysis_mode in VALID_MODES else "balanced"
    model_name = MODEL_MAPPING[analysis_mode]

    use_mock = not bool(config.CLAUDE_API_KEY)
    if use_mock:
        logger.warning("CLAUDE_API_KEY not set — using mock rule-based analysis")

    user_id = current_user.get("user_id")
    user_email = current_user.get("email")

    # Resolve analysis ID — only accept IDs created by POST /api/analyze/reserve;
    # any other client-supplied value is discarded and a fresh server UUID is used.
    analysis_id, used_reserved = await _resolve_reserved_id(request.reserved_id)

    if used_reserved:
        # Update the placeholder row created by the reserve endpoint with actual data
        await update_analysis(
            analysis_id,
            project_id=request.project_id,
            analysis_mode=analysis_mode,
        )
    else:
        # Create a pending DB record immediately so history shows in-progress analyses
        await create_analysis(
            analysis_id, request.project_id,
            user_id=user_id, user_email=user_email,
            analysis_mode=analysis_mode,
        )

    # ── Stage 1–8: Resource Discovery ─────────────────────────────────────────
    try:
        await ws_manager.send_progress(analysis_id, "Connecting to DigitalOcean...", stage=1)

        async with DigitalOceanScanner(config.DIGITALOCEAN_TOKEN) as scanner:

            # Stage 2: resolve project name
            await ws_manager.send_progress(analysis_id, "Loading Project Information...", stage=2)
            await update_analysis(analysis_id, status="running")

            projects = await scanner.get_projects()
            project = next((p for p in projects if p["id"] == request.project_id), None)
            if not project:
                raise ProjectNotFoundError(f"Project {request.project_id} not found")
            project_name = project["name"]

            # Stage 3: begin resource collection
            await ws_manager.send_progress(analysis_id, "Fetching Resources...", stage=3)
            await update_analysis(analysis_id, project_name=project_name)

            # Stage 4
            await ws_manager.send_progress(analysis_id, "Collecting Droplets...", stage=4)
            droplets = await scanner.get_droplets(request.project_id)

            # Stage 5
            await ws_manager.send_progress(analysis_id, "Collecting Volumes...", stage=5)
            volumes = await scanner.get_volumes(request.project_id)

            # Stage 6
            await ws_manager.send_progress(analysis_id, "Collecting Snapshots...", stage=6)
            snapshots = await scanner.get_snapshots(request.project_id)

            # Stage 7
            await ws_manager.send_progress(analysis_id, "Collecting Databases...", stage=7)
            databases = await scanner.get_managed_databases(request.project_id)

            # Stage 8: load balancers + floating IPs share one stage
            await ws_manager.send_progress(analysis_id, "Collecting Load Balancers...", stage=8)
            load_balancers = await scanner.get_load_balancers(request.project_id)
            floating_ips = await scanner.get_floating_ips(request.project_id)

    except InvalidTokenError:
        await _fail(analysis_id, "Invalid DigitalOcean API Token")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid DigitalOcean API Token")
    except RateLimitError:
        await _fail(analysis_id, "DigitalOcean API rate limit exceeded")
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            detail="DigitalOcean API rate limit exceeded")
    except ProjectNotFoundError:
        await _fail(analysis_id, "Project not found")
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Project not found")
    except DigitalOceanAPIError as exc:
        await _fail(analysis_id, str(exc))
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    except Exception as exc:
        logger.error(f"[{analysis_id}] Resource discovery failed: {exc}", exc_info=True)
        await _fail(analysis_id, "Failed to fetch DigitalOcean resources")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="Failed to fetch DigitalOcean resources")

    # Assemble normalized resource inventory
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
    logger.info(
        f"[{analysis_id}] Resource discovery complete — "
        f"{resource_count['total']} resources across "
        f"{len(resource_count) - 1} types"
    )

    # ── Stage 9: Monitoring Coverage + Rule Engine ────────────────────────────
    await ws_manager.send_progress(
        analysis_id, "Checking Monitoring Coverage & Running Rule Engine...", stage=9
    )

    # Monitoring check is best-effort: a timeout or API error is logged and skipped,
    # so the analysis pipeline always continues regardless of monitoring scan outcome.
    monitoring_data: List[Dict] = []
    droplet_dicts = [r for r in resources if r.get("type") == "droplet"]
    if droplet_dicts:
        try:
            monitoring_data = await asyncio.wait_for(
                MonitoringScanner(config.DIGITALOCEAN_TOKEN).scan_all_droplets_monitoring(
                    droplet_dicts
                ),
                timeout=30.0,
            )
            missing_count = sum(1 for d in monitoring_data if d["monitoring_status"] == "missing")
            unknown_count = sum(1 for d in monitoring_data if d["monitoring_status"] == "unknown")
            logger.info(
                f"[{analysis_id}] Monitoring check: {len(monitoring_data)} droplets, "
                f"{missing_count} missing agent, {unknown_count} status unknown"
            )
        except asyncio.TimeoutError:
            logger.warning(
                f"[{analysis_id}] Monitoring scan timed out (30 s) — skipping for this analysis"
            )
        except Exception as exc:
            logger.warning(
                f"[{analysis_id}] Monitoring scan failed (non-fatal): {exc}"
            )

    rule_result = RuleEngine().run(resources, resource_count, monitoring_data=monitoring_data)
    preliminary_findings = rule_result["findings"]
    logger.info(
        f"[{analysis_id}] Rule Engine complete — "
        f"{rule_result['summary']['preliminary_findings']} preliminary findings"
    )

    # Store resource count now so history shows it even if AI subsequently fails
    await update_analysis(analysis_id, resources_scanned=resource_count["total"])

    # ── Stage 10–11: Analysis (Claude or Mock) ────────────────────────────────
    ai_analysis: AIAnalysisResult | None = None
    ai_result = None
    try:
        if use_mock:
            await ws_manager.send_progress(
                analysis_id, "Analyzing Infrastructure (Mock Mode)...", stage=10
            )
            analyzer = MockAnalyzer()
        else:
            await ws_manager.send_progress(
                analysis_id,
                f"Analyzing with Claude ({analysis_mode})...",
                stage=10,
            )
            analyzer = AIAnalyzer(config.CLAUDE_API_KEY)

        ai_result = await analyzer.analyze(
            project_name=project_name,
            resources=resources,
            resource_count=resource_count,
            model_name=model_name,
            preliminary_findings=preliminary_findings,
        )

        await ws_manager.send_progress(analysis_id, "Generating Recommendations...", stage=11)
        ai_analysis = AIAnalysisResult(**ai_result)

        logger.info(
            f"[{analysis_id}] {'Mock' if use_mock else model_name} analysis complete — "
            f"{ai_analysis.summary.issues_found} issues, "
            f"{ai_analysis.summary.estimated_monthly_savings}/month savings"
        )

    except AIAuthError:
        await _fail(analysis_id, "Invalid Claude API key — check CLAUDE_API_KEY",
                    failure_reason="Invalid Claude API key")
        # 502, not 401 — the USER is authenticated; the SERVER's Claude key is wrong.
        # Returning 401 here would trigger the frontend's session-expiry interceptor.
        raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                            detail="Invalid Claude API key — check server configuration")
    except AIRateLimitError:
        await _fail(analysis_id, "Claude API rate limit exceeded — retry later",
                    failure_reason="Claude API rate limit exceeded")
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            detail="Claude API rate limit exceeded")
    except AITimeoutError:
        await _fail(analysis_id, "Claude API request timed out",
                    failure_reason="Claude API request timed out")
        raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT,
                            detail="Claude AI request timed out")
    except AIMalformedResponseError as exc:
        logger.error(f"[{analysis_id}] Claude returned malformed response: {exc}")
        await _fail(analysis_id, "Claude returned a malformed analysis response",
                    failure_reason=f"Malformed AI response: {exc}")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                            detail="Claude returned a malformed analysis response")
    except AIAnalysisError as exc:
        logger.error(f"[{analysis_id}] AI analysis failed: {exc}")
        await _fail(analysis_id, str(exc), failure_reason=str(exc))
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    except Exception as exc:
        logger.error(f"[{analysis_id}] Unexpected AI error: {exc}", exc_info=True)
        await _fail(analysis_id, "Unexpected error during AI analysis",
                    failure_reason="Internal error during AI analysis")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="AI analysis failed unexpectedly")

    # ── Stage 12: Persist results ──────────────────────────────────────────────
    await ws_manager.send_progress(analysis_id, "Storing Results...", stage=12)

    await update_analysis(
        analysis_id,
        project_name=project_name,
        resources_scanned=resource_count["total"],
        issues_found=ai_analysis.summary.issues_found if ai_analysis else 0,
        estimated_monthly_savings=(
            ai_analysis.summary.estimated_monthly_savings if ai_analysis else "$0"
        ),
        estimated_annual_savings=(
            ai_analysis.summary.estimated_annual_savings if ai_analysis else "$0"
        ),
        analysis_result=ai_result if ai_analysis else None,
        input_tokens=ai_result.get("input_tokens", 0) if ai_result else 0,
        output_tokens=ai_result.get("output_tokens", 0) if ai_result else 0,
        model_used=model_name,
        analysis_mode=analysis_mode,
        status="completed",
    )

    # ── Stage 13: Done ─────────────────────────────────────────────────────────
    await ws_manager.send_progress(analysis_id, "Analysis Complete", stage=13,
                                   status="completed")

    logger.info(f"[{analysis_id}] Pipeline complete ({'mock' if use_mock else 'live'})")

    return ProjectAnalysisResponse(
        analysis_id=analysis_id,
        project_id=request.project_id,
        project_name=project_name,
        resources=resources,
        resource_count=resource_count,
        ai_analysis=ai_analysis,
        mock=use_mock,
        input_tokens=ai_result.get("input_tokens", 0) if ai_result else 0,
        output_tokens=ai_result.get("output_tokens", 0) if ai_result else 0,
        timestamp=datetime.utcnow().isoformat(),
        model_used=model_name,
        analysis_mode=analysis_mode,
    )


# ── History ───────────────────────────────────────────────────────────────────

@app.get("/api/history", response_model=HistoryListResponse)
async def get_history(current_user: dict = Depends(get_current_user)):
    """Return the 50 most recent analyses across all users."""
    rows = await get_analyses(limit=50)
    items = [
        AnalysisHistoryItem(
            id=row.id,
            project_id=row.project_id,
            project_name=row.project_name,
            resources_scanned=row.resources_scanned,
            issues_found=row.issues_found,
            estimated_monthly_savings=row.estimated_monthly_savings,
            estimated_annual_savings=row.estimated_annual_savings,
            status=row.status,
            created_at=row.created_at.isoformat() + "Z",
            run_by=row.user_email or "",
            model_used=row.model_used or "",
            analysis_mode=row.analysis_mode or "balanced",
            failure_reason=row.failure_reason,
        )
        for row in rows
    ]
    return HistoryListResponse(analyses=items, count=len(items))


@app.get("/api/analysis/{analysis_id}", response_model=ProjectAnalysisResponse)
async def get_analysis(
    analysis_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Fetch a stored analysis by ID."""
    return await _fetch_analysis_response(analysis_id)


@app.get("/api/report/{analysis_id}", response_model=ProjectAnalysisResponse)
async def get_report(
    analysis_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Fetch a stored analysis by ID (alias used by the Report page)."""
    return await _fetch_analysis_response(analysis_id)


# ── WebSocket ─────────────────────────────────────────────────────────────────

@app.websocket("/ws/progress/{analysis_id}")
async def websocket_progress(
    websocket: WebSocket,
    analysis_id: str,
    token: Optional[str] = Query(default=None),
):
    """
    Clients connect here before or during POST /api/analyze to receive
    real-time progress messages as JSON frames.

    Requires the caller's JWT as a ?token=<jwt> query parameter.
    The connection is accepted first so the browser receives a proper WebSocket
    close frame (code 4001) rather than an opaque HTTP 403.

    The endpoint keeps the connection open until the client disconnects.
    No messages flow from client to server.
    """
    if not token or verify_token(token) is None:
        await websocket.accept()
        await websocket.close(code=4001, reason="Unauthorized")
        logger.warning(f"WS rejected — missing or invalid token for analysis {analysis_id}")
        return

    await ws_manager.connect(analysis_id, websocket)
    logger.info(f"WS client connected for analysis {analysis_id}")
    try:
        # Block until disconnect — we only push, never pull, so discard any
        # messages the client might accidentally send
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(analysis_id, websocket)
        logger.info(f"WS client disconnected from analysis {analysis_id}")


# ── Error handler ─────────────────────────────────────────────────────────────

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail, "status_code": exc.status_code},
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _fail(analysis_id: str, message: str, failure_reason: Optional[str] = None) -> None:
    """Mark analysis as failed in DB and notify WS listeners."""
    update_kwargs: dict = {"status": "failed"}
    if failure_reason:
        update_kwargs["failure_reason"] = failure_reason
    await update_analysis(analysis_id, **update_kwargs)
    await ws_manager.send_error(analysis_id, message)


async def _resolve_reserved_id(reserved_id: Optional[str]) -> tuple[str, bool]:
    """
    Validate a client-supplied reserved_id against the DB.

    Returns (analysis_id, is_reserved):
      - is_reserved=True  → reserved_id is valid; caller must UPDATE the row, not INSERT
      - is_reserved=False → reserved_id was absent/invalid; caller must INSERT a fresh row

    A valid reserved_id is one created by POST /api/analyze/reserve:
      status == "pending" AND project_id == "__reserved__"

    Any other value (arbitrary client UUID, existing analysis ID, gibberish) is
    silently discarded and a fresh server UUID is returned.
    """
    if reserved_id:
        row = await get_analysis_by_id(reserved_id)
        if row and row.status == "pending" and row.project_id == "__reserved__":
            return reserved_id, True
    return str(uuid.uuid4()), False


async def _fetch_analysis_response(analysis_id: str) -> ProjectAnalysisResponse:
    """Shared handler for GET /api/analysis/{id} and GET /api/report/{id}."""
    row = await get_analysis_by_id(analysis_id)
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Analysis not found")
    if row.analysis_result is None and row.status != "completed":
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Analysis not found")
    return ProjectAnalysisResponse(
        analysis_id=row.id,
        project_id=row.project_id,
        project_name=row.project_name,
        resources=[],
        resource_count={"total": row.resources_scanned},
        ai_analysis=AIAnalysisResult(**row.analysis_result) if row.analysis_result else None,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        timestamp=row.created_at.isoformat(),
        model_used=row.model_used or "",
        analysis_mode=row.analysis_mode or "balanced",
        failure_reason=row.failure_reason,
    )


# ── Dev entrypoint ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
