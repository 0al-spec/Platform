# Hosted Managed Operations

Platform owns the transport-neutral contract for moving SpecSpace managed
operations from a local backend subprocess boundary to a hosted or queue-backed
worker. The queue is an adapter. Existing Platform wrappers remain the only
execution engine, and their durable output reports remain lifecycle authority.

## Contracts

The CLI exposes the canonical operation registry:

```bash
.venv/bin/python scripts/platform.py managed-operation contract
```

The registry contract is `platform.managed-operation.registry.v1`. It contains
the twelve operation ids currently exposed by SpecSpace together with their
fixed Platform command family, typed input refs, output reports, side-effect
class, lock scopes, timeout, replay policy, and confirmation requirement.

Every operation after initialization requires a `ready` durable workspace
binding. `workspace_initialization_execute` is the single bootstrap exception:
it accepts a validated `planned` or `ready` binding because its purpose is to
materialize the ready initialization evidence. The exception is declared in the
operation registry as `binding_requirement: planned_or_ready`; workers must not
infer or extend it to another operation.

An immutable queue request uses:

```text
artifact_kind: platform_hosted_managed_operation_request
contract_ref: platform.hosted-managed-operation.request.v1
```

A transport status record uses:

```text
artifact_kind: platform_hosted_managed_operation_receipt
contract_ref: platform.hosted-managed-operation.receipt.v1
```

Transport receipts are observability evidence only. A `succeeded` queue receipt
cannot advance Product Workspace lifecycle unless it cites validated Platform
output reports with matching digests.

## Request Materialization

Build a request by supplying a ready durable workspace binding and every
required input from the selected operation definition:

```bash
.venv/bin/python scripts/platform.py managed-operation request \
  --operation-id repair_rerun_publish \
  --workspace-binding runs/pantry/platform_product_workspace_initialization_execution_report.json \
  --workspace-binding-ref runs/platform_product_workspace_initialization_execution_report.json \
  --input runs/platform_product_repair_rerun_execution_report.json=runs/pantry/platform_product_repair_rerun_execution_report.json \
  --output runs/pantry/hosted_repair_publication_request.json
```

The local paths after `=` are used only to read and hash inputs. They are never
persisted in the request. Queue-safe artifacts contain logical refs, media type,
artifact kind when available, byte size, and SHA-256.

Validate a stored request before enqueueing it:

```bash
.venv/bin/python scripts/platform.py managed-operation validate-request \
  --request runs/pantry/hosted_repair_publication_request.json
```

## Durable Queue Adapter

The first durable adapter uses SQLite for local development, integration tests,
and single-worker recovery drills:

```bash
.venv/bin/python scripts/platform.py managed-operation queue-init \
  --database .platform/managed-operations.sqlite3
.venv/bin/python scripts/platform.py managed-operation enqueue \
  --database .platform/managed-operations.sqlite3 \
  --request runs/pantry/hosted_repair_publication_request.json
.venv/bin/python scripts/platform.py managed-operation status \
  --database .platform/managed-operations.sqlite3 \
  --request-id 'managed-operation://pantry/repair_rerun_publish/…' \
  --include-events
```

SQLite is not the horizontally scaled production backend. It establishes the
adapter behavior and supports deterministic tests before the PostgreSQL adapter
is deployed. The store persists immutable request documents, idempotency keys,
leases, workspace/operation locks, receipts, and an append-only transition log.

The production adapter uses PostgreSQL row leases and `FOR UPDATE SKIP LOCKED`:

```bash
.venv/bin/python scripts/platform.py managed-operation queue-init \
  --queue-adapter postgresql \
  --database-url-file /run/secrets/managed-operation-database-url
```

Install `requirements-hosted.txt` in service and worker images. PostgreSQL is
required for multi-worker deployments; SQLite remains restricted to local and
single-worker integration use. Production service/worker argv must contain only
the database URL file path, never the URL or password itself.

Expired leases are handled by policy:

- read-only inspection and dry-run operations may be requeued within their
  attempt limit;
- consume-on-attempt, publication, workspace initialization, approval, and Git
  review operations are quarantined for reconciliation or a new operator
  request;
- an expired non-dry-run Git review is never blindly retried.

Queue transitions and their audit events are written atomically. The generic
worker runtime receives a typed executor adapter; it does not accept a command,
working directory, or environment from the queue request.

Concurrent enqueue is idempotent at the PostgreSQL constraint boundary. The
adapter inserts with `ON CONFLICT DO NOTHING` and then reloads the winning row;
it must not rely on locking a row that does not exist yet. Transport retries
using the same request return the current receipt rather than a database error.

## Fixed Platform Executor

The worker entry point leases at most one request and routes it through the
fixed adapter for its registered operation id:

```bash
.venv/bin/python scripts/platform.py managed-operation worker-once \
  --database .platform/managed-operations.sqlite3 \
  --artifact-root ../SpecGraph \
  --state-dir ../SpecSpace/.specspace-dev/state \
  --specgraph-dir ../SpecGraph \
  --worker-id local-candidate-worker
```

The long-running production entry point is `managed-operation worker`. It uses
the same fixed adapter, performs lease recovery before each cycle, and sleeps
only when the queue is idle.

Container liveness heartbeat runs independently from the synchronous execution
cycle. A bounded operation may legitimately occupy the worker for several
minutes; the health file continues to receive fresh non-secret heartbeat
records while the Platform wrapper runs. Lease ownership and authoritative
operation completion remain separate queue/report checks.

Worker roots are deployment configuration, not request fields. The adapter:

1. Reloads the binding source and verifies its pinned digest and revision.
2. Resolves every registry input beneath the configured state, runs, or
   SpecGraph roots and verifies its digest, size, media type, and artifact kind.
3. Reloads digest-pinned confirmation evidence for non-dry-run Git review.
4. Builds one fixed Platform argument list for the selected operation id.
5. Runs the wrapper with the registry timeout and no request-provided argv,
   environment, cwd, or output path.
6. Requires every expected Platform report and records its digest before the
   queue may mark the operation `succeeded`.

All twelve SpecSpace managed operations have an adapter. Repair rerun remains a
fixed two-phase `plan` then `execute` operation. The worker lease defaults to 600
seconds so the current bounded two-phase operation fits within one lease; an
expired lease still fails closed and enters normal recovery policy.

## Hosted Enqueue Service

SpecSpace must not import Platform modules, open the queue database, or start a
Platform subprocess in hosted mode. Platform therefore exposes a narrow HTTP
boundary:

```bash
export PLATFORM_MANAGED_OPERATION_TOKEN="$(openssl rand -hex 32)"
.venv/bin/python scripts/platform.py managed-operation serve \
  --database .platform/managed-operations.sqlite3 \
  --artifact-root ../SpecGraph \
  --state-dir ../SpecSpace/.specspace-dev/state \
  --specgraph-dir ../SpecGraph \
  --host 127.0.0.1 \
  --port 8091
```

The authenticated API provides:

- `POST /v1/managed-operations` for materialize-and-enqueue;
- `GET /v1/managed-operations/status?request_id=...` for transport status;
- `GET /v1/health` for non-secret contract/adapter readiness.

The POST body contains only `operation_id`, `workspace_id`, binding source ref,
logical input refs, and optional opaque operator/confirmation refs. The service
resolves files beneath worker-owned roots, computes all digests, builds the v1
request, and then enqueues it. It rejects unknown fields, so raw idea text,
argv, local paths, environment values, and output overrides cannot be sent by a
SpecSpace client.

The bearer token is read from `PLATFORM_MANAGED_OPERATION_TOKEN` (or another
explicit environment variable name). It is never accepted as a CLI argument or
returned by health/status. Non-loopback deployment requires TLS or an
authenticated private service network.

## Standalone Single-Node Runtime

Use `docker-compose.hosted-managed-runtime.example.yml` when Platform hosted
execution runs on a dedicated VM or small single-node server instead of inside
the full local 0AL Compose topology. The runtime contains exactly three
services:

```text
PostgreSQL
Platform managed-operation HTTP service
Platform managed-operation worker
```

Build the multi-architecture Python 3.12 runtime image and validate the
fail-closed Compose contract before starting it:

```bash
docker build --file Dockerfile.hosted-managed \
  --tag 0al/platform-hosted-managed:local .
make hosted-managed-runtime-compose-contract
```

The Compose file requires these deployment values:

```bash
export PLATFORM_MANAGED_OPERATION_IMAGE=0al/platform-hosted-managed:local
export PLATFORM_MANAGED_OPERATION_ALLOWLIST=review_status_execute
export PLATFORM_MANAGED_OPERATION_ARTIFACT_ROOT=/srv/0al/specgraph
export PLATFORM_MANAGED_OPERATION_STATE_DIR=/srv/0al/state
export PLATFORM_MANAGED_OPERATION_TOKEN_FILE=/srv/0al/secrets/managed-operation-token
export PLATFORM_MANAGED_OPERATION_DB_PASSWORD_FILE=/srv/0al/secrets/managed-operation-db-password
export PLATFORM_MANAGED_OPERATION_DATABASE_URL_FILE=/srv/0al/secrets/managed-operation-database-url
export PLATFORM_MANAGED_OPERATION_GITHUB_TOKEN_FILE=/srv/0al/secrets/managed-operation-github-token

docker compose --project-name platform-managed \
  --file docker-compose.hosted-managed-runtime.example.yml up --detach
```

Do not place secret values in `.env`, Compose YAML, image layers, or queue
requests. With non-Swarm Docker Compose, secret sources are bind-mounted and
retain host ownership and mode. For the default image user (`uid=1000`,
`gid=1000`), provision them as root-owned, group-readable files:

```bash
sudo chown root:1000 /srv/0al/secrets/managed-operation-*
sudo chmod 0440 /srv/0al/secrets/managed-operation-*

# The worker runs as uid/gid 1000 and writes authoritative reports here.
sudo chown -R 1000:1000 /srv/0al/specgraph
```

The HTTP port is published on `127.0.0.1` only. Put TLS or an authenticated
private network in front of it before connecting a remote SpecSpace instance.
The service receives the artifact root read-only; only the worker can write
authoritative reports. Both Platform containers use a read-only root
filesystem, drop Linux capabilities, and disable privilege escalation.

For a review-status canary, copy only the workspace binding, portable promotion
execution report, and queue-safe canary request needed by that operation. Do not
copy an entire developer `runs/` tree. Product review status can use validated
embedded `git_review` evidence containing the GitHub pull request URL, number,
branch, and explicit non-dry-run status; it does not require a Mac- or
workstation-local candidate worktree or open-review report.

After a host reboot, require all three containers to be healthy, verify
`GET /v1/health`, and run strict recovery:

```bash
docker compose --project-name platform-managed \
  --file docker-compose.hosted-managed-runtime.example.yml ps

docker compose --project-name platform-managed \
  --file docker-compose.hosted-managed-runtime.example.yml \
  exec managed-operation-worker \
  python3 scripts/platform.py managed-operation recover \
    --queue-adapter postgresql \
    --database-url-file /run/secrets/managed_operation_database_url \
    --max-attempts 3 \
    --strict
```

Re-enqueueing the same replay-safe canary request must return the existing
terminal receipt with the same `request_id`, `idempotency_key`, and attempt
number. It must not execute the operation a second time. PostgreSQL data and
workspace reports must remain present after the reboot.

## Production Rollout And Sign-Off

The clean-VM runtime is staging evidence. A production deployment uses
`docker-compose.hosted-managed-production.example.yml` and is not signed off
until its TLS, backup, reboot, replay, SpecSpace cutover, and rollback evidence
passes the final audit.

### Provisioning boundary

Provision DNS and a certificate for a dedicated managed-operation origin. Do
not reuse the public SpecSpace origin or expose port `8091`. The production
profile publishes only TLS ingress on port `443`; Caddy proxies to the internal
Platform service, which continues to require its bearer token.

All runtime images must be immutable digest refs:

```bash
export PLATFORM_MANAGED_OPERATION_IMAGE='ghcr.io/0al-spec/platform@sha256:<digest>'
export PLATFORM_MANAGED_OPERATION_POSTGRES_IMAGE='postgres@sha256:<digest>'
export PLATFORM_MANAGED_OPERATION_INGRESS_IMAGE='caddy@sha256:<digest>'
export PLATFORM_MANAGED_OPERATION_ALLOWLIST=review_status_execute
export PLATFORM_MANAGED_OPERATION_ARTIFACT_ROOT=/srv/0al/specgraph
export PLATFORM_MANAGED_OPERATION_STATE_DIR=/srv/0al/specspace-state
export PLATFORM_MANAGED_OPERATION_BACKUP_ROOT=/srv/0al/backups
```

`deploy/hosted-managed/production.env.example` contains the complete non-secret
environment inventory. It may be copied to a root-readable deployment env file,
but the referenced secret values remain separate files and must never be added
to that env file.

Create independent service, database, and GitHub credentials. The GitHub token
for the first canary needs read-only pull-request/repository metadata only. It
must not have repository write, workflow, administration, package-write, or
organization authority. Provide a certificate and private key through separate
files:

```bash
export PLATFORM_MANAGED_OPERATION_TOKEN_FILE=/srv/0al/secrets/service-token
export PLATFORM_MANAGED_OPERATION_DB_PASSWORD_FILE=/srv/0al/secrets/database-password
export PLATFORM_MANAGED_OPERATION_DATABASE_URL_FILE=/srv/0al/secrets/database-url
export PLATFORM_MANAGED_OPERATION_GITHUB_TOKEN_FILE=/srv/0al/secrets/github-token
export PLATFORM_MANAGED_OPERATION_TLS_CERTIFICATE_FILE=/srv/0al/secrets/tls-certificate.pem
export PLATFORM_MANAGED_OPERATION_TLS_PRIVATE_KEY_FILE=/srv/0al/secrets/tls-private-key.pem

sudo chown root:1000 /srv/0al/secrets/*
sudo chmod 0440 /srv/0al/secrets/*
sudo chown -R 1000:1000 \
  "$PLATFORM_MANAGED_OPERATION_ARTIFACT_ROOT" \
  "$PLATFORM_MANAGED_OPERATION_STATE_DIR" \
  "$PLATFORM_MANAGED_OPERATION_BACKUP_ROOT"
```

Secret values must not appear in `.env`, Compose YAML, shell history, queue
requests, canary reports, or container image layers. Rotate them by atomically
replacing the corresponding file and recreating only the consumers that read
it. Service-token rotation must update SpecSpace and Platform in one bounded
cutover. Database credential rotation must update PostgreSQL first, then both
database secret files, then recreate service, worker, and maintenance
containers. Never reuse the service bearer token as a GitHub or database token.

Run the fail-closed host preflight as root so ownership checks are meaningful:

```bash
sudo --preserve-env .venv/bin/python \
  scripts/hosted_managed_production_preflight.py \
  --service-url https://managed.example.org \
  --output /srv/0al/evidence/production-preflight.json
```

The preflight report contains no secret values, paths, or local filesystem
metadata. It requires exact read-only canary scope, `0440` root/runtime-group
secret files, digest-pinned images, a clean HTTPS URL, and runtime-owned data
directories.

### Start and probe

Validate and start the production profile:

```bash
make hosted-managed-production-contract
make hosted-managed-production-compose-smoke
docker compose --project-name platform-managed-production \
  --file docker-compose.hosted-managed-production.example.yml config >/dev/null
docker compose --project-name platform-managed-production \
  --file docker-compose.hosted-managed-production.example.yml up --detach

.venv/bin/python scripts/hosted_managed_production_probe.py \
  --service-url https://managed.example.org \
  --compose-file "$PWD/docker-compose.hosted-managed-production.example.yml" \
  --project-name platform-managed-production \
  --output /srv/0al/evidence/probe-before-reboot.json
```

The bounded Compose smoke starts the real Caddy, PostgreSQL, service, and worker
profile with a one-day self-signed fixture certificate and a temporary local
registry so even the test image is addressed by digest. It enqueues no managed
request and removes containers, registry, and volumes afterward.

The probe requires all four runtime services to be healthy, PostgreSQL as the
queue adapter, a fresh worker heartbeat, and exactly
`review_status_execute` in service health. The report is public-safe and omits
Compose paths and credentials.

Initial operational targets are diagnostic objectives, not an external SLA:

- alert immediately on any quarantined request or expanded allowlist;
- alert after two failed probes or a worker heartbeat older than 30 seconds;
- alert when a read-only canary does not terminate within its bounded window;
- run a read-only canary at least daily during rollout and after each deploy;
- run strict recovery and queue-drain audit after unclean shutdowns;
- retain private backup reports with the encrypted off-host backup they pin.

### Private backup and restore smoke

Stop new enqueueing and stop the worker after its current lease before backup.
The backup tool rejects queued/leased/running jobs, active workspace locks,
symlinks, concurrent artifact changes, and an existing backup id. It stores a
transaction-consistent versioned export of the three queue tables plus a
digest-inventoried private archive of `runs/` artifacts. It never includes
secret files.

Run the isolated maintenance profile explicitly; it is not started by normal
`up`:

```bash
backup_id="production-$(date -u +%Y%m%dT%H%M%SZ)"
docker compose --project-name platform-managed-production \
  --file docker-compose.hosted-managed-production.example.yml \
  --profile maintenance run --rm managed-operation-maintenance \
  python3 scripts/hosted_managed_runtime_backup.py backup \
    --database-url-file /run/secrets/managed_operation_database_url \
    --artifact-root /workspace/SpecGraph \
    --backup-root /backups \
    --backup-id "$backup_id"

docker compose --project-name platform-managed-production \
  --file docker-compose.hosted-managed-production.example.yml \
  --profile maintenance run --rm managed-operation-maintenance \
  python3 scripts/hosted_managed_runtime_backup.py restore-smoke \
    --database-url-file /run/secrets/managed_operation_database_url \
    --backup-root /backups \
    --backup-id "$backup_id" \
    --output "/backups/$backup_id/restore-smoke-report.json"
```

`restore-smoke` creates a temporary PostgreSQL database, restores the versioned
queue export, compares every table count, verifies every archived artifact
digest without extracting unsafe paths, then forcibly removes the temporary
database. It has no authority to restore over production. Copy the entire
private backup directory to encrypted off-host storage; copying only its public
summary is not a backup.

### Canary, reboot, replay, and rollback

Use an open review PR and a workspace-bound, queue-safe
`review_status_execute` request. Run the existing canary through the public TLS
origin with its bearer token file and with host-local artifact access so output
bytes are checked against receipt digests:

```bash
.venv/bin/python scripts/platform.py managed-operation canary \
  --service-url https://managed.example.org \
  --auth-token-file "$PLATFORM_MANAGED_OPERATION_TOKEN_FILE" \
  --request /srv/0al/canary/review-status-request.json \
  --artifact-root "$PLATFORM_MANAGED_OPERATION_ARTIFACT_ROOT" \
  --output /srv/0al/evidence/canary.json \
  --format json
```

Verify SpecSpace in hosted mode with `specspace product-smoke` and
`--expect-managed-mode backend_managed_ready`. Reboot the host, rerun strict
recovery, create `probe-after-reboot.json`, and submit the identical canary
request again as `replay-canary.json`. The replay must preserve request id,
idempotency key, output refs and `attempt=1`.

Before rollback, audit that no active job or lock remains:

```bash
docker compose --project-name platform-managed-production \
  --file docker-compose.hosted-managed-production.example.yml \
  exec -T managed-operation-worker \
  python3 scripts/hosted_managed_production_signoff.py queue-audit \
    --database-url-file /run/secrets/managed_operation_database_url \
    --output /workspace/SpecGraph/runs/production-queue-audit.json
```

Then disable hosted enqueueing in SpecSpace, stop the worker after drain, and
verify SpecSpace with `--expect-managed-mode read_only`. Do not copy queue rows
to a local SQLite executor. A consume-on-attempt or irreversible request needs
new operator intent after rollback.

The final sign-off command requires all evidence rather than trusting a single
green queue receipt:

```bash
.venv/bin/python scripts/hosted_managed_production_signoff.py signoff \
  --preflight /srv/0al/evidence/production-preflight.json \
  --probe-before-reboot /srv/0al/evidence/probe-before-reboot.json \
  --probe-after-reboot /srv/0al/evidence/probe-after-reboot.json \
  --canary /srv/0al/evidence/canary.json \
  --replay-canary /srv/0al/evidence/replay-canary.json \
  --recovery /srv/0al/evidence/recovery.json \
  --backup "/srv/0al/backups/$backup_id/backup-report.json" \
  --restore-smoke "/srv/0al/backups/$backup_id/restore-smoke-report.json" \
  --queue-audit /srv/0al/evidence/queue-audit.json \
  --hosted-specspace-smoke /srv/0al/evidence/specspace-hosted-smoke.json \
  --rollback-specspace-smoke /srv/0al/evidence/specspace-rollback-smoke.json \
  --output /srv/0al/evidence/production-canary-signoff.json
```

Only `production_canary_signed_off` permits a later, separate rollout proposal
for `promotion_execute_dry_run`. This sign-off does not enable that operation,
consume-on-attempt work, non-dry-run Git review, or read-model publication.

## Delivery And Recovery

Hosted execution uses **at-least-once** delivery. It must not claim exactly-once
execution. A worker must validate the contract and binding, compare current
input digests, acquire declared lock scopes, consult the idempotency ledger, run
the fixed Platform wrapper, persist result evidence atomically, and only then
acknowledge the queue message.

If a worker exits after Platform writes a report but before queue acknowledgement,
the next lease reconciles the idempotency key and report digest instead of
blindly repeating the side effect. `promotion_review_execute` additionally
requires an explicit confirmation ref and reconcile-before-retry behavior.

For `read_only_replay_allowed` and `same_request_dry_run_only`, an explicit new
operator action may use a new opaque `operator_ref`. Platform includes that ref
in the idempotency identity only for those replay-safe policies, allowing a
fresh review-status inspection or dry-run without weakening idempotency for
consume-on-attempt and irreversible operations. A transport retry must reuse
the original request and operator ref.

## Privacy And Authority

The request envelope must not contain:

- raw idea text or operator notes;
- local checkout, state, run-directory, or credential paths;
- secrets, tokens, Git credentials, or arbitrary environment variables;
- arbitrary commands, arguments, working directories, or output paths.

The browser and SpecSpace request state do not gain Platform, SpecGraph, Git,
Ontology, or publication authority. Queue acceptance also does not grant that
authority. A worker receives only the bounded authority required by the selected
allowlisted operation and deployment profile.

## Migration Boundary

Local `backend_managed` execution remains supported while hosted transport is
introduced. One operator request must be claimed by exactly one executor mode;
the local and hosted executors must not race on the same request. Production
read-only mode remains the default until a hosted worker, store, and queue are
explicitly configured and healthy.

Use a drain-and-cutover migration; do not copy SQLite queue rows into
PostgreSQL or let local and hosted executors consume the same request state:

1. Disable creation of new local managed-operation requests while keeping the
   existing local executor available for inspection.
2. Let replay-safe local work finish. Reconcile any running or expired
   consume-on-attempt operation from its authoritative Platform reports; create
   a new UI request when the old request is consumed, superseded, ambiguous, or
   quarantined.
3. Start PostgreSQL, initialize the empty production queue, and verify database
   health before starting the hosted service or worker.
4. Start one worker profile first. Require a fresh heartbeat and a healthy
   authenticated service response before enabling hosted mode in SpecSpace.
5. Disable the local executor and enable the hosted executor in one deployment
   change. Submit a new replay-safe inspection request, then one bounded
   consume-on-attempt request, and require their authoritative Platform reports
   before declaring cutover complete.
6. Preserve the old SQLite database read-only for audit. Never replay its rows
   into PostgreSQL and never infer lifecycle completion from either queue alone.

Rollback is also a drain operation. Stop new hosted enqueueing, stop workers
after their current lease, recover expired leases, and reconcile or quarantine
all non-terminal requests. Only after the PostgreSQL queue has no `queued`,
`leased`, or `running` jobs may SpecSpace disable hosted mode and re-enable the
local executor. Consume-on-attempt and non-dry-run Git review work requires a
new operator request after rollback; it must not be copied or blindly retried.

The minimum recovery drill must demonstrate:

- a replay-safe expired lease is requeued and can be leased by another worker;
- an expired consume-on-attempt lease is quarantined;
- workspace locks are shared across PostgreSQL connections;
- service health becomes unavailable when PostgreSQL is unavailable;
- queue `succeeded` does not advance SpecSpace without the expected durable
  Platform report.

For a Compose-capable host, use the `hosted-managed` deployment profile. It
adds PostgreSQL, the authenticated enqueue/status service, a long-running
worker, shared workspace-scoped SpecGraph artifacts, and SpecSpace hosted mode:

```bash
umask 077
openssl rand -hex 32 > /secure/path/managed-operation-token
openssl rand -hex 32 > /secure/path/managed-operation-db-password
export PLATFORM_MANAGED_OPERATION_TOKEN_FILE=/secure/path/managed-operation-token
export PLATFORM_MANAGED_OPERATION_DB_PASSWORD_FILE=/secure/path/managed-operation-db-password
.venv/bin/python scripts/platform.py deploy render --profile hosted-managed
.venv/bin/python scripts/platform.py deploy up --profile hosted-managed
```

The example is a single-host topology. The service is private to the Compose
network; expose it externally only behind TLS and authenticated ingress.
