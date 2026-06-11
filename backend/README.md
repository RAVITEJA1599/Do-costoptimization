# DigitalOcean AI Cost Detective - Backend

FastAPI backend server for analyzing DigitalOcean cloud costs using Claude AI.

## Architecture

```
Client (React) 
    ↓
FastAPI Server (async)
    ├→ DigitalOcean API (resource discovery)
    ├→ Claude API (cost analysis)
    └→ PostgreSQL (persistence)
```

## Prerequisites

- Python 3.10+
- DigitalOcean Personal Access Token
- Claude API Key (for later integration)

## Setup

### 1. Install Dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 2. Configure Environment Variables

```bash
cp .env.example .env
```

Edit `.env` and add your DigitalOcean token:

```env
DIGITALOCEAN_TOKEN=dop_v1_xxxxxxxxxxxxxxxxxxxx
```

Get your token from: https://cloud.digitalocean.com/account/api/tokens

### 3. Run the Server

**Development mode** (with auto-reload):

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

**Production mode**:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
```

The API will be available at:
- **API**: `http://localhost:8000`
- **Docs**: `http://localhost:8000/docs` (interactive Swagger UI)
- **Health Check**: `http://localhost:8000/health`

## API Endpoints

### GET /api/projects

Fetch all available DigitalOcean Projects.

**Response** (200 OK):

```json
{
  "projects": [
    {
      "id": "4e1bfbc3-dc3b-4d53-8c5d-dcvt...",
      "name": "Production",
      "description": "Main production environment",
      "is_default": false,
      "created_at": "2023-01-15T10:30:00Z"
    }
  ],
  "count": 1
}
```

**Error Responses**:

- `401`: Invalid DigitalOcean API Token
- `429`: Rate limit exceeded
- `500`: Server error

---

### POST /api/analyze

Analyze a DigitalOcean Project for cost optimization.

**Request**:

```json
{
  "project_id": "4e1bfbc3-dc3b-4d53-8c5d-dcvt..."
}
```

**Response** (200 OK):

```json
{
  "project_id": "4e1bfbc3-dc3b-4d53-8c5d-dcvt...",
  "project_name": "Production",
  "resources": [
    {
      "type": "droplet",
      "id": "12345678",
      "name": "web-01",
      "region": "nyc3",
      "vcpus": 2,
      "memory": 4096,
      "disk": 80,
      "status": "active",
      "tags": ["production", "web"]
    },
    {
      "type": "volume",
      "id": "506f78a4-b1ea-11e2-82e1-3c075437c37e",
      "name": "backup-volume",
      "size_gb": 100,
      "region": "nyc3",
      "attached_to": ["12345678"],
      "status": "available"
    }
  ],
  "resource_count": {
    "droplets": 2,
    "volumes": 3,
    "snapshots": 5,
    "databases": 1,
    "load_balancers": 1,
    "floating_ips": 2,
    "total": 14
  },
  "timestamp": "2024-01-20T14:30:00.123456"
}
```

**Error Responses**:

- `400`: Missing or invalid project_id
- `401`: Invalid API token
- `404`: Project not found
- `429`: Rate limit exceeded
- `502`: DigitalOcean API error
- `500`: Server error

---

## Resource Types

The backend normalizes resources into the following types:

| Type | Fields |
|------|--------|
| **Droplet** | id, name, region, vcpus, memory, disk, status, tags |
| **Volume** | id, name, size_gb, region, attached_to, status |
| **Snapshot** | id, name, created_at, resource_type, size_gb |
| **Database** | id, name, engine, version, num_nodes, region, status |
| **Load Balancer** | id, name, region, assigned_droplet_ids, status |
| **Floating IP** | id, ip, region, assigned_to, status |

## Error Handling

The backend handles the following error scenarios:

| Error | Status | Reason |
|-------|--------|--------|
| Invalid Token | 401 | DigitalOcean API token is invalid or expired |
| Rate Limit | 429 | DigitalOcean API rate limit exceeded |
| Project Not Found | 404 | Project ID does not exist |
| API Error | 502 | DigitalOcean API is unavailable |
| Timeout | 504 | Request took too long |
| Bad Request | 400 | Invalid request parameters |

## Performance Considerations

- **Concurrent Resource Fetching**: All resource types are fetched in parallel using `asyncio.gather()`
- **Timeout**: 30-second timeout per request to prevent hanging
- **Rate Limiting**: Respects DigitalOcean API rate limits (150 requests per hour)
- **Error Recovery**: Graceful degradation if individual resource fetches fail

## Development

### Run Tests (when available)

```bash
pytest
```

### Format Code

```bash
black . --line-length 100
```

### Lint Code

```bash
flake8 . --max-line-length 100
```

## Deployment

### Docker

```bash
docker build -f Dockerfile -t do-cost-detective-backend .
docker run -p 8000:8000 -e DIGITALOCEAN_TOKEN=your_token do-cost-detective-backend
```

### Docker Compose

```bash
docker-compose up -d
```

### Kubernetes

See `k8s/` directory for deployment manifests.

## Monitoring

Check server health:

```bash
curl http://localhost:8000/health
```

View API documentation:

```
http://localhost:8000/docs
```

## Security Notes

⚠️ **Important**: Never commit `.env` file with real tokens to version control.

- Tokens are validated on every request
- HTTPS should be used in production
- Consider using API rate limiting middleware in production
- Implement request signing for API calls
- Use secrets management system (e.g., HashiCorp Vault) in production

## Troubleshooting

### Token Error

```
Error: Invalid DigitalOcean API Token
```

**Solution**: Verify token in `.env` file and ensure it has correct permissions.

### Rate Limit Error

```
Error: DigitalOcean API rate limit exceeded
```

**Solution**: Wait before making more requests. DO allows 150 requests/hour.

### Timeout Error

```
Error: Request timeout - DigitalOcean API is taking too long
```

**Solution**: DigitalOcean API is slow. Retry after a few seconds.

## Contributing

1. Create a feature branch
2. Make your changes
3. Run tests
4. Submit a pull request

## License

MIT
