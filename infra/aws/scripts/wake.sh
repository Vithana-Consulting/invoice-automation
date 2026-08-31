#!/usr/bin/env bash
# Scales the MySQL Fargate task to 1, re-associates its fixed Elastic IP
# (a fresh ENI gets created every time the task starts, but the IP itself
# never changes — see eip.tf), then resumes App Runner. Order matters: MySQL
# needs to be reachable before the app is, since the backend connects to it
# at startup.
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
CLUSTER="vithana-cluster"
DB_SERVICE="vithana-db"
APPRUNNER_SERVICE_ARN="${VITHANA_APPRUNNER_ARN:?Set VITHANA_APPRUNNER_ARN to the apprunner_service_arn Terraform output}"
MYSQL_EIP_ALLOC_ID="${VITHANA_MYSQL_EIP_ALLOC_ID:?Set VITHANA_MYSQL_EIP_ALLOC_ID to the mysql_eip_allocation_id Terraform output}"

echo "Waking $DB_SERVICE..."
aws ecs update-service --region "$REGION" --cluster "$CLUSTER" --service "$DB_SERVICE" --desired-count 1 >/dev/null
aws ecs wait services-stable --region "$REGION" --cluster "$CLUSTER" --services "$DB_SERVICE"

echo "Re-associating the fixed Elastic IP to MySQL's new ENI..."
TASK_ARN=$(aws ecs list-tasks --region "$REGION" --cluster "$CLUSTER" --service-name "$DB_SERVICE" --query 'taskArns[0]' --output text)
ENI_ID=$(aws ecs describe-tasks --region "$REGION" --cluster "$CLUSTER" --tasks "$TASK_ARN" \
  --query 'tasks[0].attachments[0].details[?name==`networkInterfaceId`].value' --output text)
aws ec2 associate-address --region "$REGION" --network-interface-id "$ENI_ID" --allocation-id "$MYSQL_EIP_ALLOC_ID" --allow-reassociation >/dev/null
echo "Done — MySQL reachable at its usual fixed IP (DATABASE_URL unchanged)."

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
