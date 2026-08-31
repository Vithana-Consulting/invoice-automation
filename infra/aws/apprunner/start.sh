#!/bin/bash
# bash, not sh: python:3.11-slim is Debian-based and ships bash by default.
#
# Runs both processes in one container (App Runner allows only one container
# per service). App Runner's health check only ever hits the frontend's port
# (3000) — see apprunner.tf — so the FRONTEND is what must stay up for the
# service to be considered healthy. The backend is retried in a loop instead
# of being allowed to take the whole container down with it.
#
# Why this matters: the backend's FastAPI lifespan (app/main.py) runs
# Base.metadata.create_all(bind=engine) at startup with no error handling.
# MySQL (a separate Fargate task, woken/slept independently — see
# scripts/wake.sh/sleep.sh) is not guaranteed to be reachable the instant
# this container boots: it might still be asleep on a fresh deploy, or
# briefly not-yet-ready during a normal wake cycle. If the backend crashed
# and took the frontend down with it (the original version of this script
# did exactly that via `wait -n`), App Runner's health check would fail and
# the whole deployment would be marked CREATE_FAILED — which is exactly
# what happened on this app's first deploy, before this fix.
set -e

cd /app/backend
until uvicorn app.main:application --host 0.0.0.0 --port 8000; do
  echo "backend exited (likely MySQL not reachable yet) — retrying in 5s" >&2
  sleep 5
done &
BACKEND_LOOP_PID=$!

cd /app/frontend
node_modules/.bin/next start -p 3000 &
FRONTEND_PID=$!

cleanup() {
  kill "$BACKEND_LOOP_PID" "$FRONTEND_PID" 2>/dev/null || true
}
trap cleanup TERM INT

# Only the frontend's exit determines the container's outcome — matches
# what App Runner's health check actually monitors.
wait "$FRONTEND_PID"
EXIT_CODE=$?
cleanup
exit "$EXIT_CODE"
