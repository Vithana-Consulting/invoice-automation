#!/usr/bin/env bash
# Scales the MySQL Fargate task to 1, updates DATABASE_URL in Secrets
# Manager with its fresh public IP (a new ENI/IP every time the task
# starts — an Elastic IP would avoid this, but AWS is rejecting EIP
# association on this account with AuthFailure, likely a new-account
# restriction; see README), force-redeploys App Runner so it picks up the
# new secret value (secrets are only read at container start), then waits
# for App Runner to come back up.
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
CLUSTER="vithana-cluster"
DB_SERVICE="vithana-db"
APPRUNNER_SERVICE_ARN="${VITHANA_APPRUNNER_ARN:?Set VITHANA_APPRUNNER_ARN to the apprunner_service_arn Terraform output}"
SECRET_ARN="${VITHANA_SECRET_ARN:?Set VITHANA_SECRET_ARN to the secret_arn Terraform output}"

echo "Waking $DB_SERVICE..."
aws ecs update-service --region "$REGION" --cluster "$CLUSTER" --service "$DB_SERVICE" --desired-count 1 >/dev/null
aws ecs wait services-stable --region "$REGION" --cluster "$CLUSTER" --services "$DB_SERVICE"

echo "Fetching MySQL's fresh public IP..."
TASK_ARN=$(aws ecs list-tasks --region "$REGION" --cluster "$CLUSTER" --service-name "$DB_SERVICE" --query 'taskArns[0]' --output text)
ENI_ID=$(aws ecs describe-tasks --region "$REGION" --cluster "$CLUSTER" --tasks "$TASK_ARN" \
  --query 'tasks[0].attachments[0].details[?name==`networkInterfaceId`].value' --output text)
MYSQL_IP=$(aws ec2 describe-network-interfaces --region "$REGION" --network-interface-ids "$ENI_ID" \
  --query 'NetworkInterfaces[0].Association.PublicIp' --output text)
echo "MySQL is at $MYSQL_IP"

echo "Updating DATABASE_URL in Secrets Manager..."
CURRENT_SECRET=$(aws secretsmanager get-secret-value --region "$REGION" --secret-id "$SECRET_ARN" --query 'SecretString' --output text)
NEW_SECRET=$(echo "$CURRENT_SECRET" | python3 -c "
import json, sys, re
d = json.load(sys.stdin)
d['DATABASE_URL'] = re.sub(r'@[^:/]+:', '@${MYSQL_IP}:', d['DATABASE_URL'])
print(json.dumps(d))
" 2>/dev/null) || NEW_SECRET=$(echo "$CURRENT_SECRET" | node -e "
const d = JSON.parse(require('fs').readFileSync(0, 'utf8'));
d.DATABASE_URL = d.DATABASE_URL.replace(/@[^:/]+:/, '@${MYSQL_IP}:');
console.log(JSON.stringify(d));
")
aws secretsmanager put-secret-value --region "$REGION" --secret-id "$SECRET_ARN" --secret-string "$NEW_SECRET" >/dev/null
echo "Done."

echo "Redeploying App Runner so it picks up the new DATABASE_URL..."
aws apprunner start-deployment --region "$REGION" --service-arn "$APPRUNNER_SERVICE_ARN" >/dev/null
echo "Waiting for App Runner to reach RUNNING..."
while true; do
  STATUS=$(aws apprunner describe-service --region "$REGION" --service-arn "$APPRUNNER_SERVICE_ARN" --query 'Service.Status' --output text)
  [ "$STATUS" = "RUNNING" ] && break
  sleep 5
done

URL=$(aws apprunner describe-service --region "$REGION" --service-arn "$APPRUNNER_SERVICE_ARN" --query 'Service.ServiceUrl' --output text)
echo ""
echo "App is up: https://$URL"
echo "This URL is STABLE across wakes — the Google OAuth redirect URI only needs registering once, not every wake."
