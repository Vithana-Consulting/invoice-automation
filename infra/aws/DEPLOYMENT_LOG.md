# Deployment log — AWS App Runner migration

Chronological record of building and deploying the App Runner + Fargate infra in
`infra/aws/`, including every real failure hit and how it was diagnosed and fixed.
`README.md` documents the *current* design and how to operate it; this document is
the *history* — why it looks the way it does, and a troubleshooting reference for
anyone who hits the same failure modes again.

## Current status (last verified)

- **App**: `https://gfh3e43cjv.us-east-1.awsapprunner.com` — `RUNNING`, verified
  working end-to-end (`POST /api/admin/login` returns `200 {"authenticated":true}`).
- **MySQL**: asleep (`desired_count=0`) — this is the normal resting state; run
  `./scripts/wake.sh` before using the app for real (login flows that touch the DB,
  invoice ingest, etc.).
- **Terraform state**: fully reconciled, `terraform plan` shows no drift.
- **Google OAuth redirect URI**: not yet registered against this URL as of this log
  entry — do that before attempting a real user login (see `README.md`).

## Architecture (see `README.md` for full detail and rationale)

```
Browser → App Runner (frontend+backend, 1 container, stable HTTPS URL)
              ↓ public internet, dynamic IP kept current by wake.sh
          MySQL (ECS Fargate Spot, EFS-backed data, password-secured)

App Runner → S3 (invoice attachments, STORAGE_BACKEND=s3)
App Runner → Secrets Manager (1 bundled secret: DB creds, JWT key, admin key,
             LLM/LlamaParse keys, Google OAuth creds)
```

Three architectures were actually tried, in order, before landing here:

1. **ECS Fargate + Caddy + sslip.io on-demand TLS** — worked, verified end-to-end
   (login page reachable, health check passing over real HTTPS). Abandoned because
   the sslip.io hostname changes every wake (new task = new IP), which meant
   re-registering the Google OAuth redirect URI before every single session.
2. **App Runner + VPC Connector** (private MySQL access) — never got a real
   deployment past `CREATE_FAILED`. Root cause below.
3. **App Runner + public MySQL access** (current) — works.

## Every real issue hit, in order

### 1. `NEXT_PUBLIC_API_URL` baked wrong into the client bundle (found by a compatibility-audit agent, before any live deploy)

Next.js inlines `NEXT_PUBLIC_*` env vars into the browser-side JS bundle at *build*
time, not runtime. The Dockerfile's default (`http://localhost:8000`) would have
made every visitor's browser try to reach `localhost` on their own machine.
**Fix**: `build-and-push.sh` explicitly overrides it to empty, so client fetches stay
relative (`/api/...`) and resolve same-origin.

### 2. AWS security group descriptions reject non-ASCII-ish punctuation

Hit **three separate times** across different resources. AWS's character-set
restriction for SG descriptions is `^[0-9A-Za-z_ .:/()#,@\[\]+=&;{}!$*-]*$` — no
em dash (—), no apostrophe ('). Each time, the fix was rewriting the description
with plain ASCII. **This is worth remembering as a recurring pattern** — any new SG
description added to this repo should be checked against that character set before
writing it.

### 3. Security group description changes force full resource replacement

Separately from #2: AWS does not allow changing an SG's **top-level** `description`
after creation — it's immutable at the API level, so Terraform's only option is
destroy-then-recreate whenever it changes. This deadlocked badly: the `efs` SG's
mount-target ENIs (which must persist unchanged) blocked its own destroy for 15+
minutes before erroring. **Fix**: never change the top-level SG `description` string
once created — `network.tf` has explicit comments on both `db` and `efs` warning
future editors not to touch those exact strings. Rule/ingress *block* descriptions
(inside `ingress {}`) don't have this restriction and can be changed freely.

### 4. `terraform destroy`/replace gets stuck on non-empty ECR repos

`aws_ecr_repository` refuses to delete a repo that still has images —
`RepositoryNotEmptyException`. Hit this for both the original 3-repo design and the
later single combined repo. **Fix**: `force_delete = true` on the repository
resource (added after hitting this twice); for repos already stuck, resolved
directly via `aws ecr delete-repository --force`.

### 5. Terraform doesn't sequence "revoke stale cross-SG rule" before "destroy the referenced SG"

When a security group (`app`) was removed from config entirely, the *other* security
groups (`db`, `efs`) that still had OLD inline ingress rules referencing it (from the
previous state) needed those rules revoked before `app` could be deleted — but
Terraform's dependency graph only tracks the *current* config's references, and
since `db`/`efs`'s new config no longer mentions `app` at all, there's no edge
telling Terraform to sequence the revoke before the destroy. Result: `app`'s destroy
hung indefinitely with `DependencyViolation`. **Fix**: manually revoked the two stale
rules via `aws ec2 revoke-security-group-ingress` — safe, since those rules weren't
in the new config anyway.

### 6. `frontend/` has no committed `public/` directory

The App Runner Dockerfile's `COPY --from=frontend-builder /frontend/public ./public`
failed outright — Docker's `COPY` errors hard on a missing source (unlike a shell
`cp` with a wildcard). **Fix**: `RUN mkdir -p public` in the builder stage before the
final-stage `COPY`.

### 7. App Runner's VPC connector doesn't support every Availability Zone

`InvalidRequestException: ... don't support App Runner services: subnet-...(use1-az3)`.
This account's `use1-az3` isn't supported. **Fix**: filtered the connector's subnet
list by `availability_zone_id` (account-portable, unlike the AZ *name* which maps
differently per account) to exclude that one AZ.

### 8. `start.sh` let a backend crash take the whole container down

The backend's FastAPI lifespan (`app/main.py`) runs
`Base.metadata.create_all(bind=engine)` with **no error handling** at startup. If
MySQL isn't reachable yet (asleep on a fresh deploy, or briefly not-ready during a
wake), this raises and crashes the process. The original `start.sh` used
`wait -n $BACKEND_PID $FRONTEND_PID` — either process exiting killed both. Since App
Runner's health check only ever polls the **frontend's** port, a backend crash
silently failed the whole deployment as `CREATE_FAILED`, with no useful error message
anywhere. **Fix**: `start.sh` now retries the backend in a loop
(`until uvicorn ...; do sleep 5; done`); only the frontend's own exit determines the
container's fate.

Verified directly via local Docker (matching App Runner's 1 vCPU / 3GB limits) that
the fix works: frontend reports healthy in ~9s and stays healthy even while the
backend crash-loops against a deliberately-broken DB connection.

### 9. Health check timing looked tight, but wasn't actually the problem

After fix #8, deployments still failed in ~18-20s, consistently, regardless of how
generous the health check thresholds were made (tried up to a 100s budget). This
**ruled out timing entirely** — the failure was fast and deterministic, not a
threshold being exhausted. (The health check settings were still loosened as cheap
insurance and left in place: 10s interval, 5s timeout, 10 consecutive failures
allowed.)

### 10. The real cause: App Runner + VPC Connector needs a NAT Gateway, full stop

**Diagnosis method**: deployed a trivial `python -m http.server` image — zero app
code, zero DB calls — to the *exact same* App Runner service configuration (same
VPC connector, same IAM roles, same health check). It failed identically. This
proved conclusively that nothing about the app image was at fault; the problem was
the shared networking configuration itself.

**Root cause**: once an App Runner service has a VPC connector attached for egress,
*all* of its outbound traffic routes through that VPC — not just the traffic meant
for the VPC (MySQL). The connector's subnets had no NAT Gateway (deliberately
omitted to save ~$32/mo), so there was no path to the internet at all once VPC
egress was configured — App Runner's own service apparently needs some baseline
outbound connectivity even for a trivial container, unrelated to whatever the app
itself does.

**Fix chosen**: dropped the VPC connector entirely rather than pay for a NAT
Gateway. MySQL is now reached over the public internet, secured by its password
instead of network isolation (see `README.md`'s security tradeoff section for the
full reasoning and mitigations). This was a deliberate cost-vs-security tradeoff
decision, not a default — the NAT Gateway + VPC connector version is the "correct"
architecture if this ever needs to be more than an internal tool.

### 11. AWS rejects Elastic IP association on this account

The natural fix for "Fargate tasks get a new IP every restart" is an Elastic IP,
re-associated to the new ENI on each wake. Implemented this (`eip.tf`) — but
`aws ec2 associate-address` failed with `AuthFailure: You do not have permission to
access the specified resource`, even using **root credentials that own both the EIP
and the target ENI**, and even after retrying past what would be a normal
eventual-consistency delay. This looks like a new/lightly-used-AWS-account
restriction on certain EC2 actions — this same account also needed App Runner
"activated" (`SubscriptionRequiredException`, resolved itself before deployment,
never explained). **Not something fixable from Terraform or the CLI** — would need
AWS Support / account verification to lift, if it's even liftable.

**Fix chosen**: removed the EIP entirely. `wake.sh` now reads MySQL's fresh public
IP after every wake, writes it into `DATABASE_URL` in Secrets Manager directly
(`aws secretsmanager put-secret-value`), then force-redeploys App Runner
(`aws apprunner start-deployment`) so the running container actually picks up the
new value — Secrets Manager values are only read at container start, so updating
the secret alone doesn't affect an already-running instance. This costs a few extra
minutes per wake (an App Runner deployment takes 1-3 minutes) compared to what a
fixed IP would allow. **Revisit if the AWS account restriction ever gets resolved**
— switching back to a fixed IP would remove this wake-time cost.

### 12. Terraform silently failed to fully reconcile two resources after a config change

After removing Cloud Map (`service_discovery.tf`) and its `service_registries` block
reference from the ECS `db` service, and after changing the `db` security group's
ingress source, a `terraform apply` reported success — but live inspection afterward
showed **both** changes hadn't actually taken effect on the real AWS resources:

- The ECS service still had a `serviceRegistries` entry pointing at the now-deleted
  Cloud Map service. This silently blocked every new MySQL task launch: ECS reported
  `desiredCount: 1, runningCount: 0` with **zero** tasks (not even pending), no
  error surfaced anywhere, and `rolloutState: COMPLETED` despite 0 running tasks.
- The `db` security group still only allowed ingress from the (deleted)
  `apprunner_connector` security group, not the intended `0.0.0.0/0` — causing
  MySQL connections to time out (not "connection refused" — the security group was
  silently dropping packets, not actively rejecting them).

Both were fixed directly via AWS CLI (`aws ecs update-service --service-registries
"[]"`; `revoke-security-group-ingress` + `authorize-security-group-ingress`) without
waiting for another `terraform apply` cycle. **A subsequent `terraform plan` showed
no drift after these manual fixes** — meaning Terraform's own state already agreed
with the *intended* config; it was specifically the *apply* step that didn't fully
push some updates through to the live AWS resources. Worth watching for on any
future `apply` touching these two resources: **always verify the live resource
matches config after a security-group-source or service-registries change, don't
just trust "Apply complete."**

### 13. `wake.sh` never checked for PAUSED before redeploying

After the dynamic-IP rework (#11), `wake.sh` was changed to unconditionally call
`aws apprunner start-deployment` so the fresh `DATABASE_URL` would always be picked
up — but the resume-from-PAUSED check that existed in an earlier version got dropped
in that rewrite. `start-deployment` requires the service to already be `RUNNING`;
called against a service `sleep.sh` had actually paused, it would fail outright.
Caught by re-reading the script's actual logic rather than by hitting the failure
directly. **Fix**: `wake.sh` now checks status first, calls `resume-service` (and
waits for `RUNNING`) only if actually `PAUSED`, then *always* force-redeploys
afterward regardless — a resumed service comes back running whatever secret values
were baked into its last deployment, not the one just written to Secrets Manager.

## Operational runbook

See `README.md`'s "Day to day" section for the actual commands. Summary:

```bash
export VITHANA_APPRUNNER_ARN=$(terraform output -raw apprunner_service_arn)
export VITHANA_SECRET_ARN=$(terraform output -raw secret_arn)

./scripts/wake.sh      # MySQL up, DATABASE_URL updated, App Runner redeployed+resumed
./scripts/status.sh    # check current state
./scripts/sleep.sh     # MySQL down, App Runner paused — stops billing
```

## What's still open (see `README.md`'s "Known limitations" for the full list)

- MySQL is internet-reachable (accepted tradeoff, not a bug)
- MySQL's IP is dynamic, not fixed (blocked by the AWS account EIP restriction)
- Gmail OAuth credential files aren't wired into S3
- Google OAuth redirect URI needs one-time manual registration against the current
  App Runner URL before real user login will work
- Integration credentials still base64-"encoded", not real encryption (pre-existing
  app-level TODO)
