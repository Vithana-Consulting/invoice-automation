#!/usr/bin/env bash
# Scales both services back to 0 — this is what actually stops billing for
# compute. Run this when you're done with a session.
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
CLUSTER="vithana-cluster"

aws ecs update-service --region "$REGION" --cluster "$CLUSTER" --service vithana-app --desired-count 0 >/dev/null
aws ecs update-service --region "$REGION" --cluster "$CLUSTER" --service vithana-db --desired-count 0 >/dev/null

echo "Both services scaled to 0. Compute billing stops once tasks finish draining (~30-60s)."
