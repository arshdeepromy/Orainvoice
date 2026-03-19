#!/bin/sh
# Quick rebuild of the frontend container after code changes.
# Usage: ./scripts/rebuild-frontend.sh
#
# This builds the React app into static files and restarts the
# frontend nginx container. Takes ~15-30 seconds depending on cache.

set -e

echo "Building frontend..."
docker compose build frontend

echo "Restarting frontend container..."
docker compose up -d frontend

echo "Done. Refresh your browser."
