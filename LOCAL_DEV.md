# QUICK START — Local Development on MSI Raider GE75

## Prerequisites
- Python 3.11+ (py -3 --version)
- Node.js 18+ (node --version)
- pip install -r requirements.txt
- cd frontend && npm install

## First Time Setup
.env file has been created with MIRA_AUTH_MODE=none (auth bypassed for local dev).

## Verify Everything Works
```cmd
verify_mua_v10.bat
```
This runs unit tests, starts the API, hits the classifier endpoints, and checks the frontend files.

## Run Full Stack
Terminal 1 (backend):
```cmd
set PYTHONPATH=%CD%
py -3 -m uvicorn mira.api.app:app --reload --port 8000
```

Terminal 2 (frontend):
```cmd
cd frontend
npm run dev
```

Browser: http://localhost:8080/mua-v10

## What Works Without GovCloud
- MUA V10 classifier (pure Python, no DB/LLM needed)
- Frontend dev server + all UI pages
- Unit tests

## What Needs GovCloud / Postgres
- MIUL Builder (needs Postgres)
- MIRA Query / BSMH (needs Anthropic API key + Postgres)
- M&P Plan Generator (needs Anthropic API key)
- Gas Compatibility (needs FAISS vector store)

## Architecture Reminder
- Frontend port 8080 → proxies /api/* to backend port 8000 (strips /api prefix)
- MUA V10 router mounted at /mua/v10 AND /api/mua/v10
- Frontend API client uses /api/mua/v10 (goes through vite proxy)
