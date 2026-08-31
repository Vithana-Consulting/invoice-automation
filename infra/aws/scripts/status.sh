#!/usr/bin/env bash
set -euo pipefail
REGION="${AWS_REGION:-us-east-1}"
CLUSTER="vithana-cluster"

aws ecs describe-services --region "$REGION" --cluster "$CLUSTER" \
  --services vithana-app vithana-db \
  --query 'services[].{name:serviceName,desired:desiredCount,running:runningCount,status:status}' \
  --output table
