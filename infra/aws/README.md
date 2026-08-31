# AWS deployment — App Runner + Fargate (internal use)

**App**: frontend+backend combined into one container (see `apprunner/`), deployed to
**AWS App Runner** — gives a stable `https://*.awsapprunner.com` URL with TLS handled
automatically, no Caddy/reverse-proxy machinery needed.

**Database**: MySQL runs as an ECS Fargate Spot task (App Runner has no database
hosting and no persistent-volume equivalent), reached from App Runner over a
VPC Connector via Cloud Map private DNS (`db.vithana.internal`).

**File storage**: invoice attachments live in S3 (`STORAGE_BACKEND=s3` in the app —
App Runner has no EFS-equivalent mount, so this replaced the EFS volume the earlier
all-Fargate design used).

Estimated cost: ~$5-10/mo storage/secrets/logs fixed, plus App Runner + Fargate Spot
compute only while both are actually running.

## Why this replaced the earlier Caddy/sslip.io Fargate design

That design worked (verified end-to-end) but needed real complexity to get TLS: a
Caddy sidecar, on-demand certificate issuance, and a `sslip.io`-derived hostname that
changed every wake — which in turn meant **re-registering the Google OAuth redirect
URI before every single session**, since Google requires an exact pre-registered
match and won't accept a moving target. App Runner's URL is permanent, so that
redirect URI is registered **once**.

Tradeoff: App Runner's "pause" is a **manual** API call (`aws apprunner pause-service`
/ `resume-service`), not automatic idle-detection — operationally the same shape as
toggling ECS `desired_count`, just a different API. The win here is the stable URL
and zero TLS complexity, not extra cost savings.

## One-time setup

```bash
cd infra/aws
cp terraform.tfvars.example terraform.tfvars
# fill in real secrets in terraform.tfvars — never commit this file

terraform init
terraform apply    # creates the ECR repo, S3 bucket, EFS (mysql only), secrets, VPC connector, App Runner service, ECS db service

# Build and push the combined app image into the ECR repo just created
./scripts/build-and-push.sh

# Set app_image in terraform.tfvars to the printed ECR URI, then:
terraform apply
```

Get the App Runner service ARN once, and export it for the day-to-day scripts:

```bash
export VITHANA_APPRUNNER_ARN=$(terraform output -raw apprunner_service_arn)
```

## Register the Google OAuth redirect URI (one time only)

```bash
terraform output apprunner_url
```

Add `<that URL>/api/auth/google/callback` to Google Cloud Console → Credentials →
your OAuth Client → Authorized redirect URIs. Then update the app's own runtime
config once (it's DB-backed, not env-var-backed — see `CLAUDE.md`'s Runtime
Configuration section):

```bash
curl -X PUT "$(terraform output -raw apprunner_url)/api/admin/config" \
  -H "X-Admin-Key: <admin_api_key from tfvars>" -H "Content-Type: application/json" \
  -d "{\"FRONTEND_URL\": \"$(terraform output -raw apprunner_url)\", \"GOOGLE_REDIRECT_URI\": \"$(terraform output -raw apprunner_url)/api/auth/google/callback\"}"
```

Unlike the sslip.io setup, **this never needs to change again** — the URL is stable.

## Day to day

```bash
export VITHANA_APPRUNNER_ARN=$(terraform output -raw apprunner_service_arn)  # once per shell session
./scripts/wake.sh      # resumes App Runner, scales db to 1
./scripts/status.sh    # check what's currently running
./scripts/sleep.sh     # pauses App Runner, scales db to 0 — this is what stops billing
```

## Deploying new code

```bash
./scripts/build-and-push.sh
aws apprunner start-deployment --service-arn "$VITHANA_APPRUNNER_ARN"
```

(`auto_deployments_enabled = false` in `apprunner.tf` — deploys are explicit, matching
the ECS `force-new-deployment` pattern the earlier design used, so an unrelated
`docker push` never surprise-redeploys.)

## What this deliberately skips, and why

- **No ALB** — App Runner has its own built-in HTTPS endpoint, no separate load
  balancer needed.
- **No NAT Gateway** — the MySQL Fargate task gets a public IP directly from the
  default VPC's subnets (needed to pull `mysql:8.0` with no NAT); App Runner reaches
  it privately via the VPC Connector.
- **No RDS** — MySQL runs as a Fargate Spot task with data on EFS, instead of paying
  for an always-on managed instance.
- **Fargate Spot, not on-demand** (for MySQL) — ~70% cheaper; acceptable since this
  isn't customer-facing and a rare Spot interruption just means re-running `wake.sh`.

## Known limitations (fine for internal use, would need fixing for anything customer-facing)

- App Runner pause/resume is manual, not traffic-triggered — see the tradeoff note
  above.
- Cold start after `wake.sh`: App Runner resume + the Tesseract/LibreOffice-heavy
  image booting both take some time; the MySQL Fargate task also needs to reach
  healthy before the app can serve real requests.
- Gmail OAuth `credentials.json`/`token.json` files (mounted as local files in the
  original docker-compose setup) aren't wired into this deployment — Gmail ingest
  needs those added to S3 (or another mechanism) manually if you need it here.
- Integration credentials are still base64-"encoded", not encrypted (a pre-existing
  app-level TODO, see `CLAUDE.md`) — fine for an internal tool, not for production
  with a real customer's credentials.
- S3 attachment storage was added by an agent-driven change to `backend/app/` — see
  that change's own notes for exactly which files were touched and the DB `file_path`
  convention chosen for S3-stored objects.
