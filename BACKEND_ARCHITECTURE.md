# Backend Architecture - DigitalOcean AI Cost Detective

## Design Principles

This backend follows these architectural principles:

1. **Async-First**: All I/O operations use async/await for high concurrency
2. **Loose Coupling**: Modular design with clear separation of concerns
3. **Fail-Safe**: Graceful error handling with meaningful error messages
4. **Observability**: Comprehensive logging for debugging and monitoring
5. **Scalability**: Stateless design enables horizontal scaling
6. **Security**: API token validation on every request

---

## Technology Stack

| Layer | Technology | Rationale |
|-------|-----------|-----------|
| Framework | **FastAPI** | Modern, async, automatic OpenAPI docs, high performance |
| Async Runtime | **httpx** | Non-blocking HTTP client for external APIs |
| Validation | **Pydantic** | Type-safe request/response models, auto-documentation |
| Environment | **python-dotenv** | Secure environment variable management |
| Server | **Uvicorn** | ASGI server, production-ready, fast startup |

### Why FastAPI?

- **Performance**: One of the fastest Python frameworks (comparable to Node.js/Go)
- **Developer Experience**: Auto-generated API docs (Swagger UI)
- **Type Safety**: Pydantic models provide runtime validation
- **Async Native**: Built on top of Starlette, designed for async operations
- **Production Ready**: Used by companies like Uber, Netflix, Microsoft

---

## Project Structure

```
backend/
├── main.py                      # FastAPI app, route handlers
├── digitalocean_scanner.py      # DigitalOcean API integration
├── models.py                    # Pydantic models for request/response
├── config.py                    # Configuration management
├── test_main.py                 # Unit tests
├── requirements.txt             # Python dependencies
├── Dockerfile                   # Container image definition
├── .dockerignore                # Docker build context exclusions
├── .gitignore                   # Git exclusions
├── .env.example                 # Environment template
└── README.md                    # Backend documentation
```

### File Responsibilities

**main.py**
- FastAPI application instance
- Route handler endpoints
- Middleware configuration (CORS, exception handling)
- Startup/shutdown events

**digitalocean_scanner.py**
- DigitalOcean REST API client
- Resource fetching logic
- Error handling and retry logic
- Async resource orchestration

**models.py**
- Pydantic data models
- Request/response schemas
- Type definitions for IDE autocompletion

**config.py**
- Centralized configuration
- Environment variable loading
- Multi-environment support (dev/staging/prod)

---

## API Design

### Endpoints Overview

```
GET  /health               → Health check
GET  /api/projects         → List all projects
POST /api/analyze          → Analyze a project
```

### Request/Response Flow

```
Client Request
    ↓
FastAPI Router
    ↓
Route Handler (async function)
    ↓
DigitalOceanScanner (async)
    ↓
HTTP Client (httpx)
    ↓
DigitalOcean API
    ↓
Response Parsing
    ↓
Pydantic Model Validation
    ↓
HTTP Response (JSON)
    ↓
Client
```

---

## Error Handling Strategy

### Error Categories

| Error | Status | Cause | Client Action |
|-------|--------|-------|----------------|
| **Invalid Token** | 401 | Token is invalid/expired | Reconfigure token |
| **Rate Limited** | 429 | Too many requests | Exponential backoff |
| **Not Found** | 404 | Project doesn't exist | Check project ID |
| **Bad Request** | 400 | Invalid parameters | Fix request payload |
| **API Error** | 502 | DO API unavailable | Retry later |
| **Timeout** | 504 | Request too slow | Check network |
| **Server Error** | 500 | Unexpected error | Check logs |

### Error Response Format

```json
{
  "error": "Invalid DigitalOcean API Token",
  "status_code": 401,
  "details": "Optional additional context"
}
```

### Exception Hierarchy

```python
DigitalOceanAPIError (base)
├── InvalidTokenError
├── RateLimitError
├── ProjectNotFoundError
└── TimeoutError
```

---

## Data Flow: Analyzing a Project

### Step 1: Validate Request

```
POST /api/analyze
{
  "project_id": "xyz123"
}
         ↓
Pydantic validates JSON
         ↓
Extract project_id
         ↓
Check if project_id is non-empty
```

### Step 2: Authenticate

```
Read DIGITALOCEAN_TOKEN from config
         ↓
Check token is set
         ↓
Add to Authorization header: "Bearer {token}"
```

### Step 3: Fetch Project Metadata

```
GET /projects
         ↓
Find project with matching ID
         ↓
Verify project exists
         ↓
Extract project_name
```

### Step 4: Parallel Resource Fetching

```
Concurrently (async):
├─ GET /droplets → [Droplet, Droplet, ...]
├─ GET /volumes → [Volume, Volume, ...]
├─ GET /snapshots → [Snapshot, ...]
├─ GET /databases → [Database, ...]
├─ GET /load_balancers → [LoadBalancer, ...]
└─ GET /floating_ips → [FloatingIP, ...]
         ↓
Wait for all to complete
         ↓
Collect results (or exceptions)
```

### Step 5: Normalize Resources

```
Convert each DO API response
         ↓
Apply Pydantic models
         ↓
Serialize to dict
         ↓
Combine into single list
         ↓
Calculate resource counts
```

### Step 6: Return Response

```json
{
  "project_id": "xyz123",
  "project_name": "Production",
  "resources": [
    {"type": "droplet", "id": "123", ...},
    {"type": "volume", "id": "456", ...}
  ],
  "resource_count": {
    "droplets": 5,
    "volumes": 3,
    "snapshots": 10,
    "databases": 1,
    "load_balancers": 1,
    "floating_ips": 2,
    "total": 22
  },
  "timestamp": "2024-01-20T14:30:00.123456"
}
```

---

## Async Architecture

### Why Async?

**Scenario**: Analyzing a project with 50 resources

**Sync approach** (sequential):
```
GET /droplets → 200ms
GET /volumes → 150ms
GET /snapshots → 300ms
GET /databases → 100ms
GET /load_balancers → 50ms
GET /floating_ips → 75ms
──────────────────────
Total: 875ms
```

**Async approach** (concurrent):
```
GET /droplets ────────► 200ms ─┐
GET /volumes ──────► 150ms ──┐ │
GET /snapshots ──────────► 300ms ─┐ (all run in parallel)
GET /databases ────► 100ms ────┘ │
GET /load_balancers ──► 50ms ──┘
GET /floating_ips ─────► 75ms ───┘
Total: 300ms (max of all) ✓ 3x faster!
```

### Implementation Details

```python
# Concurrent execution using asyncio.gather()
results = await asyncio.gather(
    droplets_task,
    volumes_task,
    snapshots_task,
    databases_task,
    load_balancers_task,
    floating_ips_task,
    return_exceptions=True  # Don't fail if one fails
)
```

---

## Resource Normalization

### Why Normalize?

DigitalOcean API responses vary in structure:

```javascript
// Raw DO API response for Droplet
{
  "id": 25489637,           // integer
  "name": "web-01",
  "region": {
    "slug": "nyc3"          // nested
  },
  "vcpus": 2,
  "memory": 4096,           // in MB
  "disk": 80,               // in GB
  "status": "active"
}

// Raw DO API response for Volume
{
  "id": "506f78a4...",      // UUID string
  "name": "data-vol",
  "size_gigabytes": 100,    // different field name
  "region": {
    "slug": "nyc3"
  },
  "droplet_ids": [123, 456] // array
}
```

**Our Normalization**: Convert to consistent format

```python
Droplet(
    type="droplet",
    id="25489637",             # Convert to string
    name="web-01",
    region="nyc3",             # Extract from nested object
    vcpus=2,
    memory=4096,
    disk=80,
    status="active",
    tags=[]
)

Volume(
    type="volume",
    id="506f78a4...",
    name="data-vol",
    size_gb=100,               # Standardized field name
    region="nyc3",
    attached_to=[123, 456],    # Normalized format
    status="available"
)
```

### Benefits

1. **Consistency**: Predictable schema for frontend
2. **Simplicity**: Single data model per resource type
3. **Extensibility**: Easy to add fields later
4. **Type Safety**: Pydantic validates at runtime

---

## Configuration Management

### Multi-Environment Support

```
Environment: ENVIRONMENT env var
├── development (default)
│   ├── DEBUG: True
│   ├── LOG_LEVEL: DEBUG
│   └── CORS: Allow localhost:3000, localhost:5173
│
├── production
│   ├── DEBUG: False
│   ├── LOG_LEVEL: INFO
│   └── CORS: Allow specific domains
│
└── testing
    ├── MOCK TOKEN
    ├── MOCK DATABASE
    └── DISABLE EXTERNAL CALLS
```

### Configuration Hierarchy

```
1. Environment variables (.env file)
2. config.py (Config class)
3. Default values in Config
4. Validation on startup
```

### Usage

```python
from config import config

# Access configuration
token = config.DIGITALOCEAN_TOKEN
log_level = config.LOG_LEVEL
cors_origins = config.CORS_ORIGINS
```

---

## Security Considerations

### Authentication

- ✓ Token validated on every request
- ✓ Token stored in environment (never in code)
- ✓ Bearer token format follows OAuth standards
- ✓ Invalid tokens return 401 immediately

### Rate Limiting

DigitalOcean API limits: **150 requests/hour**

```python
# Current: No client-side rate limiting
# TODO: Implement for production
# - Exponential backoff on 429 responses
# - Request queuing
# - Per-user rate limits
```

### CORS Security

```python
CORS_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:5173",
]

# Production: Use specific domains
# CORS_ORIGINS = ["https://yourdomain.com"]
```

### Data Validation

All inputs validated with Pydantic:

```python
class ProjectAnalysisRequest(BaseModel):
    project_id: str  # Required, must be string

# Invalid requests automatically rejected:
POST /api/analyze {"project_id": 123}  # ERROR: must be string
POST /api/analyze {}                   # ERROR: missing required field
POST /api/analyze {"project_id": ""}   # Accepted (frontend validates)
```

---

## Observability

### Logging Strategy

```python
logger.info(f"Successfully fetched {len(projects)} projects")
logger.error(f"Error fetching projects: {e}", exc_info=True)
logger.debug(f"Response from DO API: {response.json()}")
```

### Log Levels

| Level | Use Case |
|-------|----------|
| DEBUG | Detailed request/response info |
| INFO | Successful operations, milestones |
| WARNING | Recoverable issues |
| ERROR | Failed operations |
| CRITICAL | System failures |

### Structured Logging (Future Enhancement)

```python
# Current: Basic logging
logger.info("Analysis started")

# Future: Structured logging for better analysis
logger.info({
    "event": "analysis_started",
    "project_id": "xyz123",
    "timestamp": datetime.utcnow().isoformat(),
    "user_id": "user123"
})
```

---

## Performance Optimization

### Current Optimizations

1. **Async Operations**: Concurrent API calls
2. **Connection Reuse**: httpx client connection pooling
3. **Lazy Loading**: Resources fetched on-demand
4. **Error Recovery**: Graceful degradation

### Future Optimizations

```python
# 1. Response Caching
from functools import lru_cache

@lru_cache(maxsize=100)
async def get_projects_cached(self) -> List[Dict]:
    # Cache for 5 minutes
    pass

# 2. Request Batching
# Combine multiple requests into one

# 3. Pagination
# Fetch large datasets in chunks

# 4. CDN for static responses
# Cache frequently accessed data
```

---

## Testing Strategy

### Test Coverage Goals

```
Unit Tests: 80%+
- Model validation
- Error handling
- Config loading

Integration Tests: 60%+
- Endpoint responses
- DO API mocking
- Error scenarios

E2E Tests: 40%+
- Full request flows
- Real DO API (staging account)
```

### Example Tests

```python
# Unit test
def test_invalid_token_error():
    with pytest.raises(InvalidTokenError):
        scanner._validate_token("invalid")

# Integration test
async def test_get_projects_endpoint():
    response = client.get("/api/projects")
    assert response.status_code == 200
    assert "projects" in response.json()

# E2E test (with mock)
@patch('digitalocean_scanner.httpx.AsyncClient.request')
async def test_analyze_project(mock_request):
    mock_request.return_value = Mock(
        status_code=200,
        json=lambda: {"projects": [...]}
    )
    response = client.post("/api/analyze", json={"project_id": "123"})
    assert response.status_code == 200
```

---

## Scalability Architecture

### Single Instance

```
User → Nginx → FastAPI (1 process) → PostgreSQL
```

### Horizontal Scaling

```
Load Balancer (Doctl LB)
    ├─ FastAPI Instance 1
    ├─ FastAPI Instance 2
    ├─ FastAPI Instance 3
    └─ FastAPI Instance N

All instances share PostgreSQL
```

### Implementation

```yaml
# docker-compose.yml
backend:
  deploy:
    replicas: 3

# kubernetes deployment.yaml
spec:
  replicas: 3
  template:
    spec:
      containers:
      - name: backend
        image: cost-detective:latest
```

### Stateless Design

```
✓ No in-memory state
✓ All data in PostgreSQL
✓ Session tokens validated with DB
✓ Any instance can handle any request
✓ Instances can be killed/restarted without data loss
```

---

## Monitoring & Alerting

### Health Checks

```bash
# Simple health check
GET /health
Response: {"status": "healthy"}

# Database connectivity
Periodically test PostgreSQL connection

# External API connectivity
Monitor DigitalOcean API response times
```

### Metrics to Track

```
- Request latency (p50, p95, p99)
- Error rate (5xx, 4xx, 429)
- Database connection pool usage
- DO API rate limit consumption
- Memory usage
- CPU usage
```

### Alerting Rules

```
- Error rate > 5% → Alert
- Latency p99 > 10s → Alert
- DO API rate limit < 10% → Alert
- Database unavailable → Critical Alert
```

---

## Future Enhancements

### Phase 2: Database Integration

```python
# Store analysis results
@app.post("/api/analyze")
async def analyze_project(request, db):
    analysis = await analyzer.analyze(request.project_id)
    
    # Save to database
    db_analysis = Analysis(
        project_id=request.project_id,
        result=json.dumps(analysis),
        created_at=datetime.utcnow()
    )
    db.add(db_analysis)
    db.commit()
    
    return analysis
```

### Phase 3: Claude AI Integration

```python
from anthropic import AsyncAnthropic

@app.post("/api/analyze-with-ai")
async def analyze_with_claude(request):
    resources = await scanner.analyze_project(request.project_id)
    
    client = AsyncAnthropic()
    analysis = await client.messages.create(
        model="claude-opus-4-1",
        messages=[{
            "role": "user",
            "content": f"Analyze these resources for cost optimization: {resources}"
        }]
    )
    
    return analysis.content
```

### Phase 4: WebSocket Live Updates

```python
from fastapi import WebSocket

@app.websocket("/ws/analyze/{project_id}")
async def websocket_analyze(websocket: WebSocket, project_id: str):
    await websocket.accept()
    
    async for status in scanner.analyze_with_progress(project_id):
        await websocket.send_json(status)
```

---

## Deployment Checklist

- [ ] Environment variables configured
- [ ] Database migrations applied
- [ ] CORS origins updated for production domain
- [ ] Rate limiting configured
- [ ] Logging aggregation setup (e.g., ELK stack)
- [ ] Monitoring configured (Prometheus/Datadog)
- [ ] Backup strategy implemented
- [ ] SSL/TLS certificates installed
- [ ] Load balancer configured
- [ ] Auto-scaling policies set
- [ ] Disaster recovery plan documented

---

## References

- [FastAPI Documentation](https://fastapi.tiangolo.com)
- [Pydantic Documentation](https://docs.pydantic.dev)
- [Python asyncio](https://docs.python.org/3/library/asyncio.html)
- [DigitalOcean API](https://docs.digitalocean.com/reference/api/)
- [12-Factor App](https://12factor.net)
