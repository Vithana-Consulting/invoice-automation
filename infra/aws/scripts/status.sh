#!/usr/bin/env bash
set -euo pipefail
REGION="${AWS_REGION:-us-east-1}"
CLUSTER="vithana-cluster"
APPRUNNER_SERVICE_ARN="${VITHANA_APPRUNNER_ARN:?Set VITHANA_APPRUNNER_ARN to the apprunner_service_arn Terraform output}"

echo "--- App Runner ---"
aws apprunner describe-service --region "$REGION" --service-arn "$APPRUNNER_SERVICE_ARN" \
  --query 'Service.{status:Status,url:ServiceUrl}' --output table

echo "--- MySQL (ECS) ---"
aws ecs describe-services --region "$REGION" --cluster "$CLUSTER" --services vithana-db \
  --query 'services[].{name:serviceName,desired:desiredCount,running:runningCount,status:status}' \
  --output table
