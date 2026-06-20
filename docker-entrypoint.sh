#!/usr/bin/env bash
# Docker entrypoint — starts API server + docs site
set -e

echo "AKTools"
echo "  API:  http://0.0.0.0:8080/docs"
echo "  Docs: http://0.0.0.0:8081"

# Start API (background)
cd /app/src
gunicorn --bind 0.0.0.0:8080 aktools.main:app -k uvicorn.workers.UvicornWorker &

# Serve pre-built docs (foreground — keeps container alive)
python -m http.server 8081 --directory /app/src/site
