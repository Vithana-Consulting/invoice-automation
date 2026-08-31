#!/usr/bin/env bash
# Scales db (first) then app up to 1 task, waits for both to be running,
# derives the sslip.io hostnames from the app task's public IP, and prints
# the URLs to use.
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
CLUSTER="vithana-cluster"
DB_SERVICE="vithana-db"
APP_SERVICE="vithana-app"

echo "Waking $DB_SERVICE..."
aws ecs update-service --region "$REGION" --cluster "$CLUSTER" --service "$DB_SERVICE" --desired-count 1 >/dev/null
aws ecs wait services-stable --region "$REGION" --cluster "$CLUSTER" --services "$DB_SERVICE"

echo "Waking $APP_SERVICE..."
aws ecs update-service --region "$REGION" --cluster "$CLUSTER" --service "$APP_SERVICE" --desired-count 1 >/dev/null
aws ecs wait services-stable --region "$REGION" --cluster "$CLUSTER" --services "$APP_SERVICE"

TASK_ARN=$(aws ecs list-tasks --region "$REGION" --cluster "$CLUSTER" --service-name "$APP_SERVICE" --query 'taskArns[0]' --output text)
ENI_ID=$(aws ecs describe-tasks --region "$REGION" --cluster "$CLUSTER" --tasks "$TASK_ARN" \
  --query 'tasks[0].attachments[0].details[?name==`networkInterfaceId`].value' --output text)
PUBLIC_IP=$(aws ec2 describe-network-interfaces --region "$REGION" --network-interface-ids "$ENI_ID" \
  --query 'NetworkInterfaces[0].Association.PublicIp' --output text)

# sslip.io: <label>.<ip-with-dashes>.sslip.io resolves to that literal IP.
# Lets Caddy get a real Let's Encrypt cert with no domain purchase and no
# per-wake DNS update — see infra/aws/caddy/Caddyfile.
IP_DASHED=$(echo "$PUBLIC_IP" | tr '.' '-')
APP_HOST="app.${IP_DASHED}.sslip.io"
API_HOST="api.${IP_DASHED}.sslip.io"

echo ""
echo "App is up."
echo "Frontend: https://$APP_HOST"
echo "Backend:  https://$API_HOST"
echo ""
echo "First request triggers on-demand cert issuance (a few seconds extra on top of the usual 20-40s cold start)."
echo "IMPORTANT: this hostname changes every wake. Add it to Google Cloud Console -> Credentials -> your OAuth"
echo "Client -> Authorized redirect URIs (as https://$API_HOST/api/auth/google/callback) BEFORE trying to log in,"
echo "or Google will reject the login with redirect_uri_mismatch."

# Keep FRONTEND_URL / GOOGLE_REDIRECT_URI correct for OAuth even though the
# hostname changes every wake — these are runtime-editable via the admin API.
ADMIN_KEY="${VITHANA_ADMIN_API_KEY:-}"
if [ -n "$ADMIN_KEY" ]; then
  echo ""
  echo "Updating FRONTEND_URL / GOOGLE_REDIRECT_URI runtime config..."
  curl -sf --retry 5 --retry-delay 3 -X PUT "https://$API_HOST/api/admin/config" \
    -H "X-Admin-Key: $ADMIN_KEY" -H "Content-Type: application/json" \
    -d "{\"FRONTEND_URL\": \"https://$APP_HOST\", \"GOOGLE_REDIRECT_URI\": \"https://$API_HOST/api/auth/google/callback\"}" \
    >/dev/null && echo "Done." || echo "Warning: failed to update runtime config (backend may still be starting — retry manually if needed)."
else
  echo "Set VITHANA_ADMIN_API_KEY to auto-update FRONTEND_URL/GOOGLE_REDIRECT_URI on each wake."
fi
