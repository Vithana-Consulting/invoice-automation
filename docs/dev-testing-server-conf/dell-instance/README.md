# Dev Testing Server — Dell Instance

Setup notes for running the full Vithana invoice-automation stack (frontend + backend + MySQL) in Docker on a Windows 11 host, exposed to the local Wi-Fi subnet so any device on the same network can reach it.

- **Host:** Windows 11 Pro 10.0.22631
- **Engine:** Docker Desktop (Docker 29.4.3, Compose v5.1.3)
- **LAN interface:** `Wi-Fi 2` — `192.168.68.113/24` (Public profile)
- **Date:** 2026-05-12

---

## 1. Goal

> Run frontend, backend, and MySQL as Docker containers on a developer laptop, and make those services reachable from any device on the same Wi-Fi subnet (browser, curl, mobile QA, ping).

Single-host dev/test setup — not production. No HTTPS, no Caddy, no backup sidecar. Production deployment uses `docker-compose.prod.yml` and is documented separately under `DEPLOYMENT.md`.

---

## 2. Starting state

The repository already shipped:

| File | What it gave us |
|------|----------------|
| `backend/Dockerfile` | Python 3.11-slim + tesseract + poppler, runs `uvicorn app.main:application` on `0.0.0.0:8000` |
| `frontend/Dockerfile` | Node 20-alpine, `npm install` + `npm run build` + `npm start` on port 3000 |
| `docker-compose.yml` | Three-service stack (`backend`, `frontend`, `db`) with volume mounts |
| `docker-compose.prod.yml` | Production variant with Caddy reverse proxy and B2 backup sidecar |

Missing on this machine:

- `backend/.env`
- `backend/credentials.json` (Google OAuth client secrets)
- `backend/token.json` (Gmail OAuth token cache)

The existing compose file referenced all three as bind mounts — running `docker compose up` blindly would either fail or create empty directories where files were expected.

---

## 3. Methodology

### 3.1 Architecture target

```
┌──────────────────── Windows host (192.168.68.113) ────────────────────┐
│                                                                       │
│  Docker Desktop                                                       │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │  bridge network: invoice-automation_default                     │  │
│  │                                                                 │  │
│  │  frontend ─── backend ──────► db (MySQL 8)                      │  │
│  │  :3000       :8000                                              │  │
│  └────┬─────────────┬──────────────────────────────────────────────┘  │
│       │             │                                                 │
│  0.0.0.0:3000   0.0.0.0:8000   (db: no host port — internal only)     │
└───────┼─────────────┼─────────────────────────────────────────────────┘
        │             │
        ▼             ▼                Windows Defender Firewall
        ──────────────────────────►    rules: TCP 3000, TCP 8000,
        Subnet 192.168.68.0/24         ICMPv4 echo (any profile)
```

Key design decisions:

1. **Compose-managed bridge network.** Backend reaches MySQL by service name `db` over the internal docker network. We do not need to publish MySQL to the host.
2. **MySQL stays internal** to the docker network. No `ports:` entry. Reduces the attack surface on a shared Wi-Fi.
3. **Publish frontend and backend on `0.0.0.0`** explicitly so other hosts on the LAN can reach them. Docker Desktop's default port publishing already binds to `0.0.0.0`, but writing it explicitly in `docker-compose.yml` documents the intent.
4. **Bake `NEXT_PUBLIC_API_URL` at build time** rather than runtime. Next.js inlines `NEXT_PUBLIC_*` constants into the JS bundle during `next build`, so a runtime env var is too late. The frontend `Dockerfile` now accepts it as an `ARG`.
5. **Backend's `FRONTEND_URL` matches the LAN URL** so CORS lets the LAN-served frontend talk to the backend.

### 3.2 Why these specific values

- **LAN IP `192.168.68.113`** — picked the active Wi-Fi interface. Hyper-V vSwitches (`172.27.x` / `172.28.x`) were skipped; those are private to the WSL2 / Hyper-V networks and not reachable by other physical devices.
- **No host port for MySQL** — user accepted the "internal only" option to avoid exposing `accounting/accounting` on the LAN.
- **`Profile=Any` on firewall rules** — required because the Wi-Fi profile on this machine is `Public`. Rules scoped to `Private,Domain` would not have taken effect.

---

## 4. Step-by-step process executed

### Step 1 — Discovery

```powershell
# Identify Docker
docker --version           # Docker 29.4.3
docker compose version     # v5.1.3

# Identify the LAN IPv4 to bind to
Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
  $_.PrefixOrigin -in 'Dhcp','Manual' -and
  $_.IPAddress -notlike '169.*' -and $_.IPAddress -notlike '127.*'
}
# → 192.168.68.113 on Wi-Fi 2

# Check for prerequisites
Test-Path .\backend\.env             # False
Test-Path .\backend\credentials.json # False
Test-Path .\backend\token.json       # False
```

### Step 2 — Minimal `backend/.env`

Created with placeholder LLM keys (parser will fail until real keys are dropped in, but the rest of the stack boots). `FRONTEND_URL` set to the LAN URL so CORS will let the LAN-served frontend hit the backend.

### Step 3 — Frontend Dockerfile rework

```dockerfile
# Added between COPY . . and RUN npm run build
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
```

This makes the API URL a build-time parameter so `next build` can inline it into the static bundle.

### Step 4 — `docker-compose.yml` adjustments

| Change | Reason |
|--------|--------|
| Removed `version: "3.8"` | Compose v2+ ignores it and warns |
| `ports: "0.0.0.0:3000:3000"` / `"0.0.0.0:8000:8000"` | Explicit LAN bind |
| Dropped `db` `ports:` entry | MySQL stays internal |
| `build.args.NEXT_PUBLIC_API_URL: http://192.168.68.113:8000` for frontend | Bake LAN API URL into the Next build |
| `FRONTEND_URL: http://192.168.68.113:3000` for backend | Match CORS to where the frontend is actually served |
| Removed bind mounts for `credentials.json` / `token.json` | Files don't exist on this host; per `CLAUDE.md` Google OAuth creds now live in the `integrations` table, so the legacy mounts aren't needed for a fresh boot |

### Step 5 — `docker compose up -d --build`

First attempt failed mid-build. See [§5 Difficulties](#5-difficulties-faced).

After fixes:

```powershell
docker compose up -d --build

docker compose ps
# backend    Up   (healthy)   0.0.0.0:8000->8000/tcp
# db         Up   (healthy)   3306/tcp, 33060/tcp     (no host port)
# frontend   Up               0.0.0.0:3000->3000/tcp
```

### Step 6 — Verify host-local + own-LAN-IP reachability

```powershell
Invoke-WebRequest http://localhost:8000/health        # 200, database: healthy
Invoke-WebRequest http://192.168.68.113:8000/health   # 200, same response
Invoke-WebRequest http://192.168.68.113:3000          # 307 → /login (expected unauth redirect)
```

Reaching the service through its own LAN IP proves Docker's port publisher is bound to `0.0.0.0`. It does **not** prove other hosts can reach it — Windows Defender Firewall still has to allow inbound packets.

### Step 7 — Windows Defender Firewall rules

The PowerShell session was not elevated, so rules were created via `Start-Process … -Verb RunAs` (triggers UAC).

```powershell
New-NetFirewallRule -DisplayName "Vithana Docker Frontend (3000)" `
  -Direction Inbound -Action Allow -Protocol TCP -LocalPort 3000 -Profile Any
New-NetFirewallRule -DisplayName "Vithana Docker Backend (8000)" `
  -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8000 -Profile Any
New-NetFirewallRule -DisplayName "Vithana ICMP Echo (LAN ping)" `
  -Direction Inbound -Action Allow -Protocol ICMPv4 -IcmpType 8 -Profile Any
```

`-Profile Any` is non-obvious but essential here — see [§5.3](#53-firewall-rule-profile-mismatch).

---

## 5. Difficulties faced

### 5.1 Frontend build failed: `useSearchParams()` without Suspense

`next build` aborted on the `(authenticated)/settings` and `(authenticated)/integrations` pages with:

```
useSearchParams() should be wrapped in a suspense boundary
```

These pages are client components (`'use client'`) that read query params for the active tab. Next 14 attempts to statically prerender them, and a `useSearchParams()` call inside a client component during prerender requires a Suspense parent.

**Considered fixes:**

1. **Refactor each page into a Suspense wrapper.** Cleanest but touches two files significantly.
2. **`export const dynamic = 'force-dynamic'`** — does not work inside a `'use client'` module. (Tried it. Same build error.)
3. **`experimental.missingSuspenseWithCSRBailout: false`** in `next.config.js` — downgrades the prerender error to a warning. Officially supported in Next 14.2.

Chose option 3 because:
- These are authenticated dashboard pages — there is zero value in statically prerendering them.
- One-line config change, contained to the frontend.
- The Suspense refactor is real product work that belongs in a feature PR, not in a Docker-setup PR.

**Follow-up TODO:** wrap both pages in `<Suspense>` properly and remove the experimental flag. Tracked as a code-hygiene item, not blocking.

### 5.2 First build silently truncated by output buffer

The initial foreground `docker compose up -d --build` hit the tool's stdout buffer cap mid-build during `npm install` and the command was cut off (exit 1) even though the build was still progressing. The backend image and MySQL pull had completed; frontend had not started copying.

**Resolution:** re-ran the command in the background with all output redirected to `docker-up.log`, so the build wasn't constrained by the shell-output channel. Did the rebuild only after confirming the backend image was reusable from cache.

### 5.3 Firewall rule profile mismatch

First firewall rule pass used the default `New-NetFirewallRule -Profile Private,Domain`. Looked correct in the rules list, but inbound traffic from LAN devices would still have been blocked because:

```powershell
Get-NetConnectionProfile | Where InterfaceAlias -eq 'Wi-Fi 2'
# NetworkCategory: Public
```

The active Wi-Fi adapter was on the **Public** profile. Two options:

- Re-categorize the network as Private (system-wide change, affects discovery / file sharing).
- Update the firewall rule to `-Profile Any` (scoped to our two ports).

Went with `Any` — minimal blast radius, just allows those specific TCP ports across all profiles.

### 5.4 PowerShell `2>&1` + native `docker` exit-code noise

Initial attempts at `docker compose up -d --build 2>&1 > log` produced PowerShell `NativeCommandError` records and set `$LASTEXITCODE` to 1 spuriously. PowerShell 5.1 wraps each stderr line from a native exe in an `ErrorRecord` even when the exe exits 0.

**Resolution:** switched to `$out = & docker compose ... 2>&1; $out | Out-File ...` — capture first, then write. Removed the stderr-merge entirely in subsequent invocations.

### 5.5 Elevation needed for firewall changes

The Claude Code shell session is not elevated, and `New-NetFirewallRule` requires admin. Worked around it by launching an elevated child PowerShell via `Start-Process -Verb RunAs -Wait` with a base64-encoded command, and writing results to a temp file the parent shell could read.

---

## 6. Final state

```
docker compose ps
SERVICE    STATUS                   PORTS
backend    Up (healthy)             0.0.0.0:8000->8000/tcp
db         Up (healthy)             3306/tcp, 33060/tcp  (internal only)
frontend   Up                       0.0.0.0:3000->3000/tcp

Get-NetFirewallRule -DisplayName "Vithana*"
DisplayName                       Enabled Profile
Vithana Docker Frontend (3000)    True    Any
Vithana Docker Backend (8000)     True    Any
Vithana ICMP Echo (LAN ping)      True    Any
```

**Verified reachable from any device on `192.168.68.0/24`:**

```bash
ping 192.168.68.113
curl http://192.168.68.113:8000/health
# browser → http://192.168.68.113:3000
```

---

## 7. Operational notes

### Restart the stack

```powershell
docker compose restart                  # restart all 3 services
docker compose restart backend          # just backend
docker compose down                     # stop + remove containers (keep volumes)
docker compose down -v                  # also wipes MySQL data — DANGER
```

### Rebuild after code changes

```powershell
# Backend Python change
docker compose up -d --build backend

# Frontend change
docker compose up -d --build frontend
```

### When the LAN IP changes (DHCP lease, new network)

1. Find the new IP: `Get-NetIPAddress -AddressFamily IPv4 | … | Where InterfaceAlias -eq 'Wi-Fi 2'`
2. Update three places in `docker-compose.yml`:
   - `backend.environment.FRONTEND_URL`
   - `frontend.build.args.NEXT_PUBLIC_API_URL`
   - `frontend.environment.NEXT_PUBLIC_API_URL`
3. Rebuild the frontend (the URL is baked into the JS bundle):

   ```powershell
   docker compose up -d --build frontend
   docker compose restart backend
   ```

### Database access

```powershell
docker exec -it invoice-automation-db-1 mysql -uaccounting -paccounting accounting_automation
```

### Logs

```powershell
docker compose logs -f backend
docker compose logs -f --tail=200 frontend
```

---

## 8. Known caveats and TODOs

| Item | Impact | When to address |
|------|--------|-----------------|
| `LLM_API_KEY=replace-me` in `backend/.env` | Invoice parsing will fail until a real OpenAI key is in place | Before first parse test |
| `LLAMAPARSE_API_KEY=replace-me` | LlamaParse fallback parser unavailable | Optional |
| No `credentials.json` mount | Legacy file-based Google OAuth won't work; per-tenant OAuth via `integrations` table still works once seeded | Before Gmail ingestion |
| `experimental.missingSuspenseWithCSRBailout: false` | Bypasses a real Next.js diagnostic; production builds keep shipping | Convert `useSearchParams()` callers to use `<Suspense>` |
| Frontend API URL is build-time, not runtime | Have to rebuild on IP change | Use a runtime config endpoint or proxy if this becomes painful |
| MySQL credentials are `accounting/accounting` | Trivially guessable | Fine for dev; rotate for any shared instance |
| JWT cookies are not `Secure` (no HTTPS) | Cookie sniffable on the LAN | Use `docker-compose.prod.yml` + Caddy when going beyond dev |
| ICMP echo allowed on all profiles | The host responds to `ping` from any network you join | Drop the rule if you take the laptop on untrusted networks |

---

## 9. Files changed for this setup

```
backend/.env                                                  (new — placeholder)
frontend/Dockerfile                                           (NEXT_PUBLIC_API_URL build arg)
frontend/next.config.js                                       (experimental flag)
docker-compose.yml                                            (LAN bind, internal MySQL, build args)
docs/dev-testing-server-conf/dell-instance/README.md          (this file)
```

Firewall rules live in Windows, not in the repo.

---

## 10. Quick reproduction on a fresh Dell laptop

```powershell
# 0. Prereqs: Docker Desktop installed and running
git clone git@github.com:Vithana-Consulting/invoice-automation.git
cd invoice-automation

# 1. Find your LAN IP, then update three URL occurrences in docker-compose.yml

# 2. Create backend/.env from the template in CLAUDE.md (fill in real LLM keys)

# 3. Build + start
docker compose up -d --build

# 4. Open firewall (elevated PowerShell)
New-NetFirewallRule -DisplayName "Vithana Docker Frontend (3000)" `
  -Direction Inbound -Action Allow -Protocol TCP -LocalPort 3000 -Profile Any
New-NetFirewallRule -DisplayName "Vithana Docker Backend (8000)" `
  -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8000 -Profile Any
New-NetFirewallRule -DisplayName "Vithana ICMP Echo (LAN ping)" `
  -Direction Inbound -Action Allow -Protocol ICMPv4 -IcmpType 8 -Profile Any

# 5. Verify from another LAN device
#    ping <host-ip>
#    curl http://<host-ip>:8000/health
#    browser → http://<host-ip>:3000
```
