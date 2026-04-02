web: gunicorn mira.api.app:app -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT --workers ${MIRA_WORKERS:-3} --timeout 120 --max-requests 1000 --max-requests-jitter 50
