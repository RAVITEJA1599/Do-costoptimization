# DigitalOcean AI Cost Detective

An AI-powered tool that investigates DigitalOcean cloud costs automatically. It scans resources within a DigitalOcean Project, detects cost issues such as over-provisioning, unused resources, and misconfigurations, and provides actionable recommendations with step-by-step fixes.

## Tech Stack

| Layer        | Technology                           |
| ------------ | ------------------------------------ |
| Frontend     | React (Vite + TypeScript + Tailwind) |
| Backend      | Python (FastAPI)                     |
| Auth         | Custom JWT Auth (bcrypt + PyJWT)     |
| Cloud Data   | DigitalOcean API / doctl CLI         |
| Cloud        | DigitalOcean                         |
| AI Analysis  | Claude API                           |
| Database     | PostgreSQL (Docker)                  |
| Live Updates | FastAPI WebSocket                    |

## Architecture

```text
                              ┌──────────────┐
                              │     USER     │
                              └──────┬───────┘
                                     │
                                     ▼
                           ┌───────────────────┐
                           │  REACT FRONTEND   │
                           └────────┬──────────┘
                                    :
                                    : Login / Signup
                                    ▼
                           ┌───────────────────┐
                           │  PYTHON BACKEND   │
                           │    (FastAPI)      │
                           │                   │
                           │  · Custom JWT Auth│
                           └───┬───────┬───┬───┘
                               :       :   :
                ┌──────────────┘       :   └──────────────┐
                :                      :                  :
                ▼                      ▼                  ▼
      ┌─────────────────┐     ┌──────────────┐    ┌──────────────┐
      │ DIGITALOCEAN API│     │   FASTAPI    │    │    CLAUDE    │
      │                 │     │  WEBSOCKET   │    │     API      │
      │ Projects        │     │  (Progress)  │    │ Cost Analysis│
      │ Droplets        │     └──────┬───────┘    └──────┬───────┘
      │ Volumes         │            :                   :
      │ Databases       │            : Live Updates      :
      │ Snapshots       │            ▼                   :
      │ Load Balancers  │    ┌───────────────┐           :
      └──────┬──────────┘    │    REACT      │           :
             :               │  (Progress    │           :
             ▼               │   Tracker)    │           :
      ┌─────────────────┐    └───────────────┘           :
      │  DIGITALOCEAN   │                                :
      │    PROJECT      │                                :
      └─────────────────┘                                :
                                                         ▼
                                                ┌──────────────┐
                                                │ POSTGRESQL   │
                                                │  (Docker)    │
                                                │              │
                                                │ · users      │
                                                │ · analyses   │
                                                └──────┬───────┘
                                                       :
                                                       : Stored Results
                                                       ▼
                                                ┌───────────────┐
                                                │    REACT      │
                                                │ Final Report  │
                                                │ Suggestions   │
                                                │ Fix Steps     │
                                                └───────────────┘
```

## Request Flow

```text
① User ─·─·─► React ─·─·─► FastAPI Auth ─·─·─► JWT (PostgreSQL)

② User selects a DigitalOcean Project ─·─·─► Python Backend

③ Python ─·─·─► DigitalOcean API / doctl ─·─·─► Fetches all resources

④ Python ─·─·─► FastAPI WebSocket ─·─·─► React (Live Progress)

⑤ Python ─·─·─► Claude API ─·─·─► Cost Analysis

⑥ Python ─·─·─► PostgreSQL ─·─·─► Stores Analysis History

⑦ React ◄·─·─·─ Final Report with Recommendations & Fix Steps
```

## What It Detects

* **Over-provisioned resources** — Droplets, Managed Databases, and Kubernetes clusters sized larger than required
* **Unused resources** — Unattached volumes, unused floating IPs, idle load balancers, and orphaned snapshots
* **Misconfigurations** — Incorrect resource sizing, unnecessary backups, unused services, and inefficient infrastructure layouts
* **Storage costs** — Excessive snapshots, unused block storage volumes, and redundant backups
* **Optimization opportunities** — Rightsizing recommendations and potential monthly savings

## Prerequisites

* DigitalOcean Personal Access Token
* Access to at least one DigitalOcean Project
* Claude API Key
* Docker & Docker Compose
* Python 3.10+
* Node.js 18+

## How to Run

### Backend

```bash
cd backend

pip install -r requirements.txt

cp .env.example .env

# Configure:
# DIGITALOCEAN_TOKEN
# CLAUDE_API_KEY
# DATABASE_URL

uvicorn main:app --reload
```

### Database

```bash
docker compose up -d postgres
```

### Frontend

```bash
cd frontend

npm install

npm run dev
```

## How It Works

1. User signs up or logs in using JWT authentication.
2. User selects a DigitalOcean Project for analysis.
3. Backend fetches infrastructure data from DigitalOcean.
4. Live scan progress is streamed to the frontend using WebSockets.
5. Resource information is sent to Claude for analysis.
6. Claude identifies cost-saving opportunities and infrastructure inefficiencies.
7. Analysis results are stored in PostgreSQL.
8. A final report is generated containing:

   * Cost findings
   * Estimated savings
   * Optimization recommendations
   * Step-by-step remediation actions
