FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.api.txt .
RUN pip install --no-cache-dir -r requirements.api.txt

COPY . .

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8080/health || exit 1

# Gunicorn with Uvicorn workers for multi-worker production.
# MIRA_WORKERS controls concurrency (default 3).
CMD ["sh", "-c", "gunicorn mira.api.app:app -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8080 --workers ${MIRA_WORKERS:-3} --timeout 120 --max-requests 1000 --max-requests-jitter 50 --access-logfile - --error-logfile -"]
