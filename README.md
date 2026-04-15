# Biomedical Research Agent (Alzheimer’s Targets)

Chat-first web app that discovers and ranks drug targets for a disease using biomedical APIs, stores evidence in Postgres, persists a knowledge graph in Neo4j, and generates an evidence-backed scientific summary with a LangGraph LLM agent.

## Stack

- **Backend**: FastAPI, Pydantic, LangGraph, OpenAI, httpx
- **Datastores**: PostgreSQL (app data, logs, evaluations), Neo4j (knowledge graph)
- **Frontend**: Angular dashboard (chat + graph + evidence views)
- **Biomedical sources**: Open Targets, UniProt, Ensembl, PubMed

## Quickstart (dev)

1) Start datastores

```bash
cd infra
docker compose up -d
```

2) Backend

```bash
cd backend
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
setx OPENAI_API_KEY "YOUR_KEY"
uvicorn app.main:app --reload --port 8000
```

3) Frontend (once generated)

```bash
cd frontend
npm install
npm start
```

## Core APIs

- `POST /api/chat`: run agent, return answer + ranked targets + evidence + graph summary + evaluation
- `GET /api/entities/{kind}/{id}`: entity profile (gene/target/protein/drug/disease)
- `GET /api/graph/traverse`: traverse graph around an entity
- `GET /api/evidence`: evidence lookup for a target

## Docker Deployment (Production)

This repo now includes production Docker assets:

- `backend/Dockerfile`
- `frontend/Dockerfile`
- `frontend/nginx.conf` (proxies `/api` to backend)
- `docker-compose.deploy.yml`
- `.env.example`

### 1) Prepare environment variables

Copy `.env.example` to `.env` and set real values:

```bash
cp .env.example .env
```

Use free managed services for cloud deployment:

- PostgreSQL: Neon or Supabase free tier
- Neo4j: Aura Free

### 2) Build and run

```bash
docker compose -f docker-compose.deploy.yml up --build -d
```

App will be available on:

- Frontend: `http://localhost`
- Backend (internal): `http://backend:8000`

### 3) Verify

```bash
docker compose -f docker-compose.deploy.yml ps
```

Open `http://localhost` and run a chat query.

## Free Cloud Deployment Strategy

For a fully free setup with Dockerized app code:

1. Deploy **backend** Docker image to a free container host.
2. Deploy **frontend** Docker image to a free container host.
3. Set backend env vars from `.env.example` using:
   - Neon/Supabase free Postgres
   - Neo4j Aura Free
4. Set `CORS_ORIGINS` to your frontend URL.

Because free plans change often, the most stable approach is:

- managed DB free tiers + your Docker containers on whichever provider currently offers free instances.

