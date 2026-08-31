#!/usr/bin/env bash
# Pauses App Runner and scales MySQL to 0. This is what actually stops
# billing for compute (App Runner: no per-vCPU/memory charge while PAUSED;
# Fargate: no charge while desired_count=0).
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
CLUSTER="vithana-cluster"
APPRUNNER_SERVICE_ARN="${VITHANA_APPRUNNER_ARN:?Set VITHANA_APPRUNNER_ARN to the apprunner_service_arn Terraform output}"

echo "Pausing App Runner service..."
aws apprunner pause-service --region "$REGION" --service-arn "$APPRUNNER_SERVICE_ARN" >/dev/null

aws ecs update-service --region "$REGION" --cluster "$CLUSTER" --service vithana-db --desired-count 0 >/dev/null

echo "App Runner pausing, MySQL scaling to 0. Compute billing stops once both finish (~30-60s)."
