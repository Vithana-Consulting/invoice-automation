#!/bin/bash
# bash, not sh: `wait -n` below is a bashism (dash's `wait` doesn't support
# it). python:3.11-slim is Debian-based and ships bash by default.
#
# Runs both processes in one container (App Runner allows only one container
# per service). If either dies, kill the other and exit non-zero so App
# Runner's health checks / restarts see the failure instead of a silently
# half-working container.
set -e

cd /app/backend
uvicorn app.main:application --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

cd /app/frontend
node_modules/.bin/next start -p 3000 &
FRONTEND_PID=$!

cleanup() {
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
}
trap cleanup TERM INT

# Exit as soon as either process exits, propagating a non-zero code if it
# was the one that failed.
wait -n "$BACKEND_PID" "$FRONTEND_PID"
EXIT_CODE=$?
cleanup
exit "$EXIT_CODE"
