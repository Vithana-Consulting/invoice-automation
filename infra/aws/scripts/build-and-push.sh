#!/usr/bin/env bash
# Builds the combined frontend+backend image (infra/aws/apprunner/Dockerfile)
# and pushes it to the ECR repo Terraform created. Run after `terraform
# apply` (the repo must exist first) and again any time you want to deploy
# new code.
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGISTRY="$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com"
TAG="${1:-latest}"

# Repo root — the Dockerfile COPYs both backend/ and frontend/, plus
# infra/aws/apprunner/start.sh, so the build context must be the root, not
# this apprunner/ subdirectory.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRY"

echo "Building combined app image..."
# NEXT_PUBLIC_API_URL must stay EMPTY — it's inlined into the browser-side
# JS bundle at build time (frontend/src/lib/api.ts), not read at runtime.
# Leaving it empty keeps client fetches relative (/api/...), which resolve
# same-origin against whatever App Runner URL the browser is actually on.
# BACKEND_INTERNAL_URL stays localhost since frontend+backend share this one
# container's network namespace (see infra/aws/apprunner/Dockerfile).
docker build \
  -f "$ROOT_DIR/infra/aws/apprunner/Dockerfile" \
  --build-arg BACKEND_INTERNAL_URL=http://localhost:8000 \
  --build-arg NEXT_PUBLIC_API_URL= \
  -t "$REGISTRY/vithana-app:$TAG" "$ROOT_DIR"
docker push "$REGISTRY/vithana-app:$TAG"

echo ""
echo "Pushed: $REGISTRY/vithana-app:$TAG"
echo ""
echo "If this is the first push, set app_image in terraform.tfvars to this value and re-run terraform apply."
echo "If you're redeploying the same tag, trigger a fresh deployment with:"
echo "  aws apprunner start-deployment --service-arn <apprunner_service_arn output>"
