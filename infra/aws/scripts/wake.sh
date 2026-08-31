#!/usr/bin/env bash
# Resumes the App Runner service and scales the MySQL Fargate task to 1.
# Order matters: MySQL first, so the app isn't reachable before its DB is.
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
CLUSTER="vithana-cluster"
DB_SERVICE="vithana-db"
APPRUNNER_SERVICE_ARN="${VITHANA_APPRUNNER_ARN:?Set VITHANA_APPRUNNER_ARN to the apprunner_service_arn Terraform output}"

echo "Waking $DB_SERVICE..."
aws ecs update-service --region "$REGION" --cluster "$CLUSTER" --service "$DB_SERVICE" --desired-count 1 >/dev/null
aws ecs wait services-stable --region "$REGION" --cluster "$CLUSTER" --services "$DB_SERVICE"

echo "Resuming App Runner service..."
STATUS=$(aws apprunner describe-service --region "$REGION" --service-arn "$APPRUNNER_SERVICE_ARN" --query 'Service.Status' --output text)
if [ "$STATUS" = "PAUSED" ]; then
  aws apprunner resume-service --region "$REGION" --service-arn "$APPRUNNER_SERVICE_ARN" >/dev/null
  echo "Waiting for App Runner to reach RUNNING..."
  while true; do
    STATUS=$(aws apprunner describe-service --region "$REGION" --service-arn "$APPRUNNER_SERVICE_ARN" --query 'Service.Status' --output text)
    [ "$STATUS" = "RUNNING" ] && break
    sleep 5
  done
else
  echo "App Runner already $STATUS (not paused) — nothing to resume."
fi

URL=$(aws apprunner describe-service --region "$REGION" --service-arn "$APPRUNNER_SERVICE_ARN" --query 'Service.ServiceUrl' --output text)
echo ""
echo "App is up: https://$URL"
echo "This URL is STABLE across wakes — the Google OAuth redirect URI only needs registering once, not every wake."
