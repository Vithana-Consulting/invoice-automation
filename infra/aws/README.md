# AWS deployment — App Runner + Fargate (internal use)

**App**: frontend+backend combined into one container (see `apprunner/`), deployed to
**AWS App Runner** — gives a stable `https://*.awsapprunner.com` URL with TLS handled
automatically, no Caddy/reverse-proxy machinery needed.

**Database**: MySQL runs as an ECS Fargate Spot task (App Runner has no database
hosting and no persistent-volume equivalent), reached from App Runner over the
**public internet on a dynamic IP that `scripts/wake.sh` keeps current** — see the
security note below for why this isn't a VPC-private connection, and why it's dynamic
rather than a fixed Elastic IP.

**File storage**: invoice attachments live in S3 (`STORAGE_BACKEND=s3` in the app —
App Runner has no EFS-equivalent mount, so this replaced the EFS volume the earlier
all-Fargate design used).

Estimated cost: ~$5-10/mo storage/secrets/logs fixed, plus App Runner + Fargate Spot
compute only while both are actually running.

## Why MySQL is reachable over the public internet, not privately via VPC

The first real deployment attempt hit a wall: App Runner's VPC Connector (needed for
private access to MySQL) routes **all** of a service's egress through the VPC once
attached — not just the traffic meant for the VPC. This app also needs real internet
access (OpenAI, LlamaParse, Google OAuth), which meant the VPC connector's subnets
needed a NAT Gateway (~$32/mo) to have any internet path at all. Confirmed this was
the actual cause by deploying a trivial `python -m http.server` image — no app code,
no DB calls — to the exact same VPC-connector service config, and it failed identically,
proving the problem was the shared networking setup, not anything in the app image.

Rather than pay for a NAT Gateway, MySQL is reachable over the public internet
instead, secured by the generated password rather than network isolation:

- **Security group**: `aws_security_group.db`'s ingress is open to `0.0.0.0/0` on
  3306 — App Runner's default (non-VPC) egress has no static/predictable source IPs
  to allow-list, so there's no narrower CIDR to restrict to.
- **Mitigations**: a strong generated password (`terraform.tfvars`, never committed);
  the task normally sits at `desired_count=0` (see `scripts/sleep.sh`), so the actual
  exposure window is only while you're using the app, not continuous.
- **Not acceptable for anything beyond an internal, low-stakes tool.** If this ever
  needs to be genuinely secure, the real fix is the NAT Gateway + VPC connector
  version (~$32/mo more), not this one.

### Why the IP is dynamic instead of a fixed Elastic IP

The obvious fix for a Fargate task getting a fresh public IP every time it starts is
an Elastic IP, re-associated to the new ENI on each wake. That's what this repo tried
first (`eip.tf`, now removed) — but **AWS rejects the EIP association on this account
with `AuthFailure`, even using root credentials that own both the EIP and the ENI**.
This looks like a new/lightly-used-account restriction on certain EC2 actions (the
same account also needed App Runner "activated" via a `SubscriptionRequiredException`
seen once earlier). If that gets resolved (AWS Support / account verification), the
EIP approach is simpler and worth switching back to.

Until then, `scripts/wake.sh` handles the dynamic IP directly: after MySQL's task is
stable, it reads the task's current public IP, updates `DATABASE_URL` in Secrets
Manager in place, then force-redeploys App Runner (`aws apprunner start-deployment`)
so the new value is actually picked up — secrets are only read at container start, so
just updating Secrets Manager alone wouldn't affect an already-running container. This
adds a few minutes to every wake (an App Runner deployment takes 1-3 minutes) compared
to what a fixed IP would allow.

The Secrets Manager resource has `lifecycle { ignore_changes = [secret_string] }` so
that `wake.sh`'s live updates survive future `terraform apply` runs — the tradeoff is
that rotating any *other* field in that secret (JWT key, etc.) via `terraform.tfvars`
won't take effect while that's in place; do it via the AWS CLI/Console directly, or
temporarily remove the lifecycle block to push a tfvars change through.

## Why App Runner over the earlier Caddy/sslip.io Fargate design

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
terraform apply    # creates the ECR repo, S3 bucket, EFS (mysql only), secrets, App Runner service, ECS db service

# Build and push the combined app image into the ECR repo just created
./scripts/build-and-push.sh

# Set app_image in terraform.tfvars to the printed ECR URI, then:
terraform apply
```

Get the App Runner service ARN and the app secret's ARN once, and export them for the
day-to-day scripts:

```bash
export VITHANA_APPRUNNER_ARN=$(terraform output -raw apprunner_service_arn)
export VITHANA_SECRET_ARN=$(terraform output -raw secret_arn)
```

**Important**: MySQL's Fargate task doesn't have a working `DATABASE_URL` until
`wake.sh` has run at least once (it's what actually sets the real value) — run
`./scripts/wake.sh` before the very first login attempt.

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
export VITHANA_SECRET_ARN=$(terraform output -raw secret_arn)                # once per shell session
./scripts/wake.sh      # scales db to 1, updates DATABASE_URL with its fresh IP, redeploys + resumes App Runner
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
  default VPC's subnets (needed to pull `mysql:8.0` with no NAT, and now also how
  App Runner reaches it) — see the security tradeoff section above for what this
  costs in exposure.
- **No RDS** — MySQL runs as a Fargate Spot task with data on EFS, instead of paying
  for an always-on managed instance.
- **Fargate Spot, not on-demand** (for MySQL) — ~70% cheaper; acceptable since this
  isn't customer-facing and a rare Spot interruption just means re-running `wake.sh`.

## Known limitations (fine for internal use, would need fixing for anything customer-facing)

- **MySQL is internet-reachable** — see the security tradeoff section above. The
  single biggest thing to fix before this could ever be customer-facing.
- **MySQL's IP is dynamic, not a fixed Elastic IP** — see the "why the IP is dynamic"
  section above (AWS is rejecting EIP association on this account). Revisit if that
  gets resolved; it would remove the need for `wake.sh` to redeploy App Runner on
  every wake.
- App Runner pause/resume is manual, not traffic-triggered — see the tradeoff note
  above.
- Cold start after `wake.sh`: MySQL needs to reach healthy, then App Runner needs a
  full redeploy (1-3 min) to pick up the new `DATABASE_URL` — slower than a fixed-IP
  wake would be.
- Gmail OAuth `credentials.json`/`token.json` files (mounted as local files in the
  original docker-compose setup) aren't wired into this deployment — Gmail ingest
  needs those added to S3 (or another mechanism) manually if you need it here.
- Integration credentials are still base64-"encoded", not encrypted (a pre-existing
  app-level TODO, see `CLAUDE.md`) — fine for an internal tool, not for production
  with a real customer's credentials.
- S3 attachment storage was added by an agent-driven change to `backend/app/` — see
  that change's own notes for exactly which files were touched and the DB `file_path`
  convention chosen for S3-stored objects.
- `start.sh` retries the backend in a loop instead of letting a crash take the whole
  container down, specifically so a slow/not-yet-updated `DATABASE_URL` at startup
  doesn't fail App Runner's health check (which only ever polls the frontend's port).
- The ECS `db` service's `serviceRegistries` can end up pointing at a deleted Cloud
  Map service if a future config change removes that block again — Terraform doesn't
  always clear this field cleanly on update. If MySQL's task stops launching after an
  `apply` with `runningCount` stuck at 0 and no new tasks appearing, check
  `aws ecs describe-services ... --query 'services[0].serviceRegistries'` for a stale
  reference and clear it directly: `aws ecs update-service ... --service-registries "[]"`.
