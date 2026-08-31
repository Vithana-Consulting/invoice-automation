#!/usr/bin/env bash
# Builds backend + frontend images and pushes them to the ECR repos Terraform
# created. Run this after `terraform apply` (repos must exist first) and
# again any time you want to deploy new code.
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGISTRY="$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com"
TAG="${1:-latest}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRY"

echo "Building backend..."
docker build -t "$REGISTRY/vithana-backend:$TAG" "$ROOT_DIR/backend"
docker push "$REGISTRY/vithana-backend:$TAG"

echo "Building frontend..."
# BACKEND_INTERNAL_URL is baked in at build time by Next.js. Since frontend
# and backend run in the same ECS task (same network namespace), localhost
# is always correct here regardless of the task's public IP.
docker build \
  --build-arg BACKEND_INTERNAL_URL=http://localhost:8000 \
  --build-arg NEXT_PUBLIC_API_URL=http://localhost:8000 \
  -t "$REGISTRY/vithana-frontend:$TAG" "$ROOT_DIR/frontend"
docker push "$REGISTRY/vithana-frontend:$TAG"

echo "Building caddy..."
docker build -t "$REGISTRY/vithana-caddy:$TAG" "$ROOT_DIR/infra/aws/caddy"
docker push "$REGISTRY/vithana-caddy:$TAG"

echo ""
echo "Pushed:"
echo "  $REGISTRY/vithana-backend:$TAG"
echo "  $REGISTRY/vithana-frontend:$TAG"
echo "  $REGISTRY/vithana-caddy:$TAG"
echo ""
echo "If this is the first push, set backend_image / frontend_image / caddy_image in terraform.tfvars to these values and re-run terraform apply."
echo "If you're redeploying the same tag, force a fresh pull with:"
echo "  aws ecs update-service --cluster vithana-cluster --service vithana-app --force-new-deployment"
