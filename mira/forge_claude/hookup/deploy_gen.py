"""Docker + Railway + Vercel config generation."""

from __future__ import annotations

import json


def generate_docker_compose(database_name: str) -> str:
    """Generate docker-compose.yml for local testing."""
    return f'''version: "3.8"

services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: {database_name}
      POSTGRES_USER: forge
      POSTGRES_PASSWORD: forge_dev
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data

  backend:
    build:
      context: ./backend
    environment:
      DATABASE_URL: postgresql://forge:forge_dev@db:5432/{database_name}
    ports:
      - "8000:8000"
    depends_on:
      - db

  frontend:
    build:
      context: ./frontend
    ports:
      - "5173:5173"
    depends_on:
      - backend

volumes:
  pgdata:
'''


def generate_backend_dockerfile() -> str:
    """Generate Dockerfile for the backend."""
    return '''FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
'''


def generate_backend_requirements() -> str:
    """Generate requirements.txt for the backend."""
    return """fastapi>=0.111.0
uvicorn[standard]>=0.30.0
pydantic>=2.7.0
pydantic-settings>=2.3.0
sqlalchemy>=2.0.0
psycopg2-binary>=2.9.0
"""


def generate_frontend_dockerfile() -> str:
    """Generate Dockerfile for the frontend."""
    return '''FROM node:20-alpine

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host"]
'''


def generate_railway_json(database_name: str) -> str:
    """Generate Railway deployment config."""
    config = {
        "$schema": "https://railway.app/railway.schema.json",
        "build": {
            "builder": "DOCKERFILE",
            "dockerfilePath": "Dockerfile",
        },
        "deploy": {
            "startCommand": "uvicorn app:app --host 0.0.0.0 --port $PORT",
            "healthcheckPath": "/api/health",
            "restartPolicyType": "ON_FAILURE",
        },
    }
    return json.dumps(config, indent=2)


def generate_vercel_json() -> str:
    """Generate Vercel deployment config."""
    config = {
        "buildCommand": "npm run build",
        "outputDirectory": "dist",
        "framework": "vite",
        "rewrites": [
            {"source": "/api/:path*", "destination": "/api/:path*"}
        ],
    }
    return json.dumps(config, indent=2)
