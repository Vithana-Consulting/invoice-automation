# AWS deployment — scale-to-zero Fargate (internal use)

Minimal-cost AWS setup for internal use: no ALB, no RDS, no NAT Gateway. Two
ECS Fargate Spot services (`app` = frontend+backend+Caddy in one task, `db` =
MySQL) that sit at `desired_count = 0` (no compute billed) until you
manually wake them.

Estimated cost: ~$5-10/mo storage/secrets/logs fixed, plus Fargate Spot
compute only while actually running (roughly $0.017/hr for both tasks
combined — a full 8-hour workday costs well under $1).

## TLS / Google OAuth

Caddy runs as a third container in the `app` task and terminates HTTPS using
[sslip.io](https://sslip.io) — `app.<ip-with-dashes>.sslip.io` and
`api.<ip-with-dashes>.sslip.io` both resolve to the task's literal public IP,
so Caddy can get a real Let's Encrypt cert via on-demand TLS with **no
domain purchase and no DNS step**. See `caddy/Caddyfile`.

**The catch**: Google rejects any OAuth redirect URI that isn't
pre-registered exactly, and the sslip.io hostname changes every wake (new
task = new IP). `wake.sh` prints the new `api.*.sslip.io` hostname —
**you must add `https://<that host>/api/auth/google/callback` to Google
Cloud Console → Credentials → your OAuth Client → Authorized redirect URIs
before logging in each session**, or you'll get `redirect_uri_mismatch`.
This is manual and doesn't automate away with Terraform (it's a Google
Console edit, not an AWS one).

If this friction becomes annoying, the fix is a real (even cheap, ~$12/yr)
domain with a Route53 record `wake.sh` updates to the new IP each time —
then you register the redirect URI **once**, permanently, instead of every
session. Worth revisiting if wakes become frequent.

## One-time setup

```bash
cd infra/aws
cp terraform.tfvars.example terraform.tfvars
# fill in real secrets in terraform.tfvars — never commit this file

terraform init
terraform apply    # creates VPC-scoped resources, ECR repos, EFS, secrets, services at 0 tasks

# Build and push the app images into the ECR repos just created
./scripts/build-and-push.sh

# Set backend_image / frontend_image in terraform.tfvars to the printed
# ECR URIs, then:
terraform apply
```

## Day to day

```bash
./scripts/wake.sh      # scales db then app to 1 task, prints the URL to use
./scripts/status.sh     # check what's currently running
./scripts/sleep.sh      # scale back to 0 when done — this is what stops billing
```

Set `VITHANA_ADMIN_API_KEY` (matches `admin_api_key` in tfvars) before
running `wake.sh` so it can auto-update `FRONTEND_URL` and
`GOOGLE_REDIRECT_URI` via the app's own runtime-config API — both change
every wake because the public IP is dynamic.

## Deploying new code

```bash
./scripts/build-and-push.sh
aws ecs update-service --cluster vithana-cluster --service vithana-app --force-new-deployment
```

## What this deliberately skips, and why

- **No ALB** — fixed ~$16-20/mo regardless of use; a raw public IP is fine
  for an internal tool with a handful of users.
- **No NAT Gateway** — fixed ~$32/mo; both tasks get a public IP directly
  from the default VPC's subnets instead.
- **No RDS** — MySQL runs as a second Fargate Spot task with data on EFS,
  instead of paying for an always-on managed instance.
- **Fargate Spot, not on-demand** — ~70% cheaper; acceptable since this
  isn't customer-facing and a rare Spot interruption just means re-running
  `wake.sh`.

## Known limitations (fine for internal use, would need fixing for anything customer-facing)

- Public IP (and sslip.io hostname) changes every wake — see the Google
  OAuth caveat above. Add a Route53 zone + a `wake.sh` step to update an A
  record if you outgrow this.
- Cold start: first request after `wake.sh` takes 20-40s while the
  Tesseract/LibreOffice-heavy backend image finishes booting, plus a few
  more seconds for Caddy's first on-demand cert issuance.
- No persistent cert cache for Caddy — since the hostname changes every
  wake anyway, a cached cert from the last session wouldn't be reusable, so
  `/data` isn't mounted to EFS. Each wake re-issues a fresh cert (fast, just
  not instant).
- Gmail OAuth `credentials.json`/`token.json` files (mounted as local files
  in the original docker-compose setup) aren't wired into this Fargate
  setup — Gmail ingest needs those added to the EFS volume manually if you
  need it here.
- Integration credentials are still base64-"encoded", not encrypted (a
  pre-existing app-level TODO, see `CLAUDE.md`) — fine for an internal tool,
  not for production with a real customer's credentials.
