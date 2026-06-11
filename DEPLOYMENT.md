# Deployment Guide - DigitalOcean AI Cost Detective

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     Production Environment                   │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌────────────────────────────────────────────────────────┐ │
│  │            Load Balancer / Reverse Proxy                │ │
│  │              (Nginx / DigitalOcean LB)                  │ │
│  └────────┬───────────────────────────┬───────────────────┘ │
│           │                           │                      │
│  ┌────────▼──────────┐    ┌───────────▼─────────┐           │
│  │   Frontend App    │    │   Backend API       │           │
│  │  (React/Vite)     │    │  (FastAPI)          │           │
│  │  - Static files   │    │  - 2-4 replicas     │           │
│  │  - CDN            │    │  - Auto-scaling     │           │
│  └───────────────────┘    └─────────┬───────────┘           │
│                                     │                        │
│                          ┌──────────▼──────────┐             │
│                          │  PostgreSQL Cluster  │             │
│                          │  - Primary + Replicas│             │
│                          │  - WAL archiving     │             │
│                          │  - Backup schedule   │             │
│                          └─────────────────────┘             │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

## Prerequisites

- DigitalOcean Account with API access
- Domain name (for production)
- SSH keys configured
- Docker & Docker Compose installed locally
- Terraform (recommended for IaC)
- kubectl (if using Kubernetes)

## Local Development

### Quick Start

```bash
# 1. Clone repository
git clone <repo>
cd Do-costoptimization

# 2. Setup environment
make setup

# 3. Start services
make up

# 4. Access the application
# Frontend: http://localhost:5173
# Backend API: http://localhost:8000
# API Docs: http://localhost:8000/docs
```

### Development Commands

```bash
# Backend only (hot-reload)
make backend-dev

# Frontend only (Vite dev server)
make frontend-dev

# Run both with tmux
make dev

# View logs
make logs

# Clean up
make clean down
```

## Docker Deployment

### Single Server (DigitalOcean Droplet)

**1. Create a Droplet**

```bash
# Create a 2GB/1vCPU Ubuntu 22.04 Droplet
doctl compute droplet create cost-detective \
  --image ubuntu-22-04-x64 \
  --size s-1vcpu-2gb \
  --region nyc3 \
  --enable-monitoring
```

**2. SSH into droplet and install Docker**

```bash
ssh root@<droplet-ip>

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh

# Install Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" \
  -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Create app directory
mkdir -p /opt/app
cd /opt/app
```

**3. Deploy application**

```bash
# Clone repository
git clone <repo> .

# Setup environment
cp .env.example .env
# Edit .env with production values
nano .env

# Start services
docker-compose up -d

# View logs
docker-compose logs -f
```

**4. Setup Nginx Reverse Proxy**

```bash
sudo apt-get install nginx certbot python3-certbot-nginx

# Create Nginx config
sudo tee /etc/nginx/sites-available/cost-detective > /dev/null <<EOF
server {
    listen 80;
    server_name yourdomain.com www.yourdomain.com;
    
    location / {
        proxy_pass http://localhost:5173;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host \$host;
        proxy_cache_bypass \$http_upgrade;
    }
    
    location /api {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF

# Enable site
sudo ln -s /etc/nginx/sites-available/cost-detective /etc/nginx/sites-enabled/

# Setup HTTPS
sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com

# Restart Nginx
sudo systemctl restart nginx
```

## Kubernetes Deployment

### Setup (DigitalOcean Kubernetes)

**1. Create DOKS cluster**

```bash
doctl kubernetes cluster create cost-detective \
  --region nyc3 \
  --node-pool "name=default;size=s-2vcpu-4gb;count=2" \
  --auto-upgrade \
  --enable-monitoring
```

**2. Configure kubectl**

```bash
doctl kubernetes cluster kubeconfig save cost-detective
```

**3. Create namespace**

```bash
kubectl create namespace cost-detective
kubectl config set-context --current --namespace=cost-detective
```

**4. Create secrets**

```bash
kubectl create secret generic do-api \
  --from-literal=token=$DIGITALOCEAN_TOKEN \
  -n cost-detective

kubectl create secret generic db-credentials \
  --from-literal=password=$DB_PASSWORD \
  -n cost-detective
```

**5. Deploy with Helm (create helm chart first)**

```bash
helm repo add cost-detective ./helm
helm install cost-detective cost-detective/cost-detective \
  -n cost-detective \
  -f values-production.yaml
```

## Monitoring & Observability

### Application Metrics

Enable Prometheus monitoring:

```yaml
# docker-compose.yml addition
prometheus:
  image: prom/prometheus
  volumes:
    - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml
  ports:
    - "9090:9090"

grafana:
  image: grafana/grafana
  ports:
    - "3000:3000"
  environment:
    - GF_SECURITY_ADMIN_PASSWORD=admin
```

### Logging

```bash
# View backend logs
docker-compose logs -f backend

# View frontend logs
docker-compose logs -f frontend

# View database logs
docker-compose logs -f postgres
```

### Health Checks

```bash
# Backend health
curl http://localhost:8000/health

# Database connectivity
docker-compose exec postgres pg_isready -U costdetective
```

## Database Management

### Backup Strategy

```bash
# Manual backup
docker-compose exec postgres pg_dump \
  -U costdetective cost_detective > backup.sql

# Restore from backup
docker-compose exec -T postgres psql \
  -U costdetective cost_detective < backup.sql
```

### Automated Backups

```bash
# Create backup script
cat > /opt/backup.sh << 'EOF'
#!/bin/bash
DATE=$(date +%Y%m%d_%H%M%S)
docker-compose exec -T postgres pg_dump \
  -U costdetective cost_detective | \
  gzip > /backups/cost_detective_${DATE}.sql.gz

# Keep only last 7 days
find /backups -name "cost_detective_*.sql.gz" -mtime +7 -delete
EOF

# Add to crontab (daily at 2 AM)
0 2 * * * /opt/backup.sh
```

## Scaling Strategies

### Horizontal Scaling

**Multiple backend replicas:**

```yaml
# docker-compose.yml
backend:
  deploy:
    replicas: 3
  ports:
    - "8000-8002:8000"
```

**Load balancing:**

```bash
# Use DigitalOcean Load Balancer
doctl compute load-balancer create \
  --name cost-detective-lb \
  --forwarding-rules entry_protocol:http,entry_port:80,target_protocol:http,target_port:8000 \
  --health-check protocol:http,port:8000,path:/health \
  --region nyc3
```

### Vertical Scaling

```bash
# Upgrade droplet size
doctl compute droplet-action resize \
  --resize-disk \
  <droplet-id> \
  --size s-2vcpu-4gb
```

## Security Best Practices

### Environment Variables

Never commit `.env` with secrets:

```bash
# Use DigitalOcean Spaces for encrypted storage
# Or use HashiCorp Vault

# In production, use:
docker-compose --env-file /secure/location/.env.prod up -d
```

### Network Security

```bash
# Create firewall rules
doctl compute firewall create cost-detective \
  --inbound-rules "protocol:tcp,ports:80,sources:addresses:0.0.0.0/0" \
  --inbound-rules "protocol:tcp,ports:443,sources:addresses:0.0.0.0/0" \
  --inbound-rules "protocol:tcp,ports:22,sources:addresses:<your-ip>" \
  --outbound-rules "protocol:tcp,ports:all,destinations:addresses:0.0.0.0/0"
```

### HTTPS/TLS

Always use HTTPS in production:

```bash
# Let's Encrypt with Certbot
sudo certbot certonly --standalone \
  -d yourdomain.com \
  -d api.yourdomain.com
```

### API Rate Limiting

Add to FastAPI:

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

@app.get("/api/projects")
@limiter.limit("30/minute")
async def get_projects(request: Request):
    ...
```

## CI/CD Pipeline

### GitHub Actions Example

```yaml
# .github/workflows/deploy.yml
name: Deploy

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Build images
        run: docker-compose build

      - name: Push to registry
        run: |
          docker login -u ${{ secrets.DOCKER_USER }} \
            -p ${{ secrets.DOCKER_PASS }}
          docker push myregistry/cost-detective:latest

      - name: Deploy to production
        run: |
          ssh ${{ secrets.PROD_HOST }} \
            'cd /opt/app && docker-compose pull && docker-compose up -d'
```

## Troubleshooting

### Backend not starting

```bash
# Check logs
docker-compose logs backend

# Common issues:
# 1. Invalid token - check .env
# 2. Port already in use - docker-compose down && docker-compose up
# 3. Database not ready - wait 10 seconds and retry
```

### Database connection issues

```bash
# Test connection
docker-compose exec backend python -c \
  "import psycopg2; psycopg2.connect('dbname=cost_detective user=costdetective host=postgres')"
```

### Memory issues

```bash
# Check resource usage
docker stats

# Increase Docker memory limit
# Update docker-compose.yml:
# deploy:
#   resources:
#     limits:
#       memory: 2G
```

## Cost Optimization

### DigitalOcean Recommendations

- Use Reserved Droplets for 35% savings
- Monitor with DigitalOcean Monitoring
- Use Backups for disaster recovery
- Consider Spaces for file storage
- Use Container Registry for image storage

### Resource Sizing

| Environment | Droplet | Memory | Storage | Cost/month |
|-------------|---------|--------|---------|-----------|
| Dev         | s-1vcpu-512mb | 512MB | 10GB | $4 |
| Staging     | s-1vcpu-2gb | 2GB | 50GB | $12 |
| Production  | s-2vcpu-4gb | 4GB | 80GB | $24 |

## Maintenance

### Regular Tasks

```bash
# Weekly: Update images
docker-compose pull
docker-compose up -d

# Monthly: Database maintenance
docker-compose exec postgres \
  pg_dump -U costdetective cost_detective > backup.sql

# Quarterly: Security updates
docker-compose down
docker system prune -a
docker-compose build --no-cache
docker-compose up -d
```

## Support & References

- DigitalOcean Docs: https://docs.digitalocean.com
- FastAPI Docs: https://fastapi.tiangolo.com
- React Docs: https://react.dev
- PostgreSQL Docs: https://www.postgresql.org/docs/
