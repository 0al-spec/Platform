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
PostgreSQL and the Platform service use only an internal backend network. The
worker has a distinct outbound network for GitHub, while Caddy has a distinct
published ingress network; worker egress and public ingress are never shared.

### Provisioning boundary

Provision DNS and a certificate for a dedicated managed-operation origin. Do
not reuse the public SpecSpace origin or expose port `8091`. The production
profile publishes only TLS ingress on port `443`; Caddy proxies to the internal
Platform service, which continues to require its bearer token.

For a disposable VPS experiment, start from Ubuntu 24.04 or Ubuntu 26.04 and paste the
versioned [`cloud-init.production.example.yaml`](../deploy/hosted-managed/cloud-init.production.example.yaml)
into the provider's Cloud-init field. The provider applies the selected SSH
public key separately. This bootstrap installs Docker/Compose, creates the
runtime directories with the expected ownership, hardens SSH, and opens only
SSH plus HTTP/HTTPS. It intentionally does **not** deploy Platform, set image
refs, clone a repository, or contain a key, token, TLS material, or database
credential.

After the host is reachable, validate the bootstrap before transferring any
runtime inputs:

```bash
ssh root@<host> 'docker compose version && sudo ufw status verbose && \
  stat -c "%U:%G %a %n" /srv/0al/{platform,specgraph,specspace-state,backups,evidence,secrets}'
```

Install the bounded checkout helper before updating either host checkout:

```bash
sudo deploy/hosted-managed/hosted-managed-checkout.sh install
sudo /usr/local/sbin/0al-hosted-managed-checkout status --repository platform
sudo /usr/local/sbin/0al-hosted-managed-checkout status --repository specgraph
```

For an update, pass the full reviewed commit explicitly with `sync`. The helper
accepts only the fixed Platform and SpecGraph repository contracts, requires a
clean worktree and exact detached commit, and executes Git through numeric
runtime uid/gid `1000:1000` with a dedicated host-local HOME. It does not add a
global `safe.directory`, create a login account, accept an arbitrary remote, or
discard local changes. Numeric execution avoids assuming that uid 1000 has the
same account name across Ubuntu/cloud-provider images.

Use the rendered environment and secret-file procedure below only after that
host-level check succeeds. A Cloud-init bootstrap is not deployment evidence
and does not enable managed operations.

### TLS provisioning and renewal

The Cloud-init baseline installs Certbot but does not request a certificate.
After the dedicated hostname has an IPv4 `A` record pointing at the host, run
the tracked provisioning helper from the Platform checkout:

```bash
sudo deploy/hosted-managed/hosted-managed-tls.sh provision \
  --domain managed.example.org \
  --email operator@example.org \
  --expected-ip 203.0.113.10
```

The helper requires exactly one IPv4 `A` record matching `--expected-ip` and no
`AAAA` record until IPv6 ingress is enabled. It requires a contact email, uses
the standalone HTTP-01 challenge on port `80`, and installs a domain-pinned
Certbot deploy hook.
It copies only that lineage into the production secret files with mode `0440`
and ownership `root:1000`. Certbot's systemd timer performs renewal; after a
successful renewal the hook atomically replaces the two runtime files and
recreates only `managed-operation-ingress` when that container is already
running. No Platform service, queue, Git, or ontology authority is granted.

Verify both the live certificate and the renewal path:

```bash
sudo /usr/local/sbin/0al-hosted-managed-tls status
sudo certbot renew --dry-run --no-random-sleep-on-renew
sudo env \
  RENEWED_DOMAINS=managed.example.org \
  RENEWED_LINEAGE=/etc/letsencrypt/live/managed.example.org \
  /etc/letsencrypt/renewal-hooks/deploy/0al-hosted-managed-tls
sudo /usr/local/sbin/0al-hosted-managed-tls status
```

`status` fails when the runtime certificate is absent or has less than 30 days
remaining. The explicit hook invocation tests permissions, the live lineage
sync, and ingress reload without copying a staging certificate into the runtime
secret files. The explicit dry-run disables Certbot's normal randomized renewal
delay so an operator receives a bounded verification result; the systemd timer
retains its randomized schedule for routine renewal. The contact email is stored
by Certbot under `/etc/letsencrypt`; it must not be added to Git, the production
environment file, or evidence reports.

All runtime images must be immutable digest refs:

```bash
export PLATFORM_MANAGED_OPERATION_IMAGE='ghcr.io/0al-spec/platform-hosted-managed@sha256:<digest>'
export PLATFORM_MANAGED_OPERATION_POSTGRES_IMAGE='postgres@sha256:<digest>'
export PLATFORM_MANAGED_OPERATION_INGRESS_IMAGE='ghcr.io/0al-spec/platform-hosted-managed-ingress@sha256:<digest>'
export PLATFORM_MANAGED_OPERATION_ALLOWLIST=review_status_execute
export PLATFORM_MANAGED_OPERATION_ARTIFACT_ROOT=/srv/0al/specgraph
export PLATFORM_MANAGED_OPERATION_STATE_DIR=/srv/0al/specspace-state
export PLATFORM_MANAGED_OPERATION_BACKUP_ROOT=/srv/0al/backups
```

Publish the two Platform-owned images through the manual **Publish Hosted
Managed Images** workflow. It builds `linux/amd64` and `linux/arm64`, emits
provenance and SBOM attestations, and uploads
`hosted-managed-image-lock-<commit>/hosted-managed-image-lock.json`. Validate
the downloaded lock before using either ref:

```bash
/usr/bin/python3 scripts/validate_hosted_managed_image_lock.py \
  hosted-managed-image-lock.json
```

Set `PLATFORM_MANAGED_OPERATION_IMAGE`,
`PLATFORM_MANAGED_OPERATION_POSTGRES_IMAGE`, and
`PLATFORM_MANAGED_OPERATION_INGRESS_IMAGE` from the validated `image_ref`
values, not from mutable tags. The lock is public-safe evidence;
it does not deploy, change the allowlist, or grant managed-operation authority.

Prefer rendering the non-secret deployment environment directly from that
validated lock instead of transcribing image refs by hand:

```bash
sudo /usr/bin/python3 scripts/render_hosted_managed_production_env.py \
  --image-lock hosted-managed-image-lock.json \
  --output /etc/0al/hosted-managed-production.env \
  --artifact-root /srv/0al/specgraph \
  --state-dir /srv/0al/specspace-state \
  --backup-root /srv/0al/backups \
  --secret-root /srv/0al/secrets \
  --ingress-bind-ip 0.0.0.0 \
  --ingress-port 443
```

The renderer validates the complete image lock, fixes the initial allowlist to
`review_status_execute`, rejects overlapping runtime/secret roots, writes the
environment atomically with mode `0440`, and never reads secret values. Run it
as root so the resulting file has the ownership expected by production
operations. Existing output is preserved unless `--overwrite` is explicit.

`deploy/hosted-managed/production.env.example` contains the complete non-secret
environment inventory. It may be copied to a root-readable deployment env file,
but the referenced secret values remain separate files and must never be added
to that env file.

Create independent service, database, and GitHub credentials. The GitHub token
for the first canary needs read-only pull-request/repository metadata only. It
must not have repository write, workflow, administration, package-write, or
organization authority. Store recovery copies in an end-to-end encrypted
password manager, then provision the runtime copies from a controlling terminal:

```bash
sudo deploy/hosted-managed/hosted-managed-secrets.sh provision
sudo deploy/hosted-managed/hosted-managed-secrets.sh status
```

The helper accepts no credential arguments or environment values. It prompts
with terminal echo disabled, requires independently generated 64-character hex
database and service credentials plus a fine-grained GitHub token, derives the
container-internal PostgreSQL URL, and atomically creates the four runtime files.
It refuses to overwrite an existing credential. `status` verifies file shape,
ownership, mode, credential independence, and database URL consistency, but
never prints credential values. Provide a certificate and private key through
the separate TLS helper described above. The resulting file inventory is:

```bash
export PLATFORM_MANAGED_OPERATION_TOKEN_FILE=/srv/0al/secrets/service-token
export PLATFORM_MANAGED_OPERATION_DB_PASSWORD_FILE=/srv/0al/secrets/database-password
export PLATFORM_MANAGED_OPERATION_DATABASE_URL_FILE=/srv/0al/secrets/database-url
export PLATFORM_MANAGED_OPERATION_GITHUB_TOKEN_FILE=/srv/0al/secrets/github-token
export PLATFORM_MANAGED_OPERATION_TLS_CERTIFICATE_FILE=/srv/0al/secrets/tls-certificate.pem
export PLATFORM_MANAGED_OPERATION_TLS_PRIVATE_KEY_FILE=/srv/0al/secrets/tls-private-key.pem

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
database secret files, then recreate PostgreSQL, service, and maintenance
containers plus the worker only when a worker profile is explicitly enabled.
Never reuse the service bearer token as a GitHub or database token.

Run the fail-closed host preflight as root so ownership checks are meaningful:

```bash
sudo --preserve-env /usr/bin/python3 \
  scripts/hosted_managed_production_preflight.py \
  --service-url https://managed.example.org \
  --output /srv/0al/evidence/production-preflight.json
```

The preflight report contains no secret values, paths, or local filesystem
metadata. It requires exact read-only canary scope, `0440` root/runtime-group
secret files, digest-pinned images, a clean HTTPS URL, runtime-owned data
directories, and a regular non-symlink SpecGraph `Makefile` beneath the artifact
root. The last check mirrors the executor input contract so an empty artifact
directory blocks deployment before any bounded worker window can open.

### Start and probe

For routine updates of an already running production profile, first synchronize
the Platform checkout to the exact `source_commit` from a newly published image
lock. Then use the bounded deployment orchestrator instead of repeating Compose
commands manually:

```bash
sudo /usr/local/sbin/0al-hosted-managed-checkout sync \
  --repository platform \
  --commit "$(jq -r .source_commit /srv/0al/evidence/hosted-managed-image-lock.json)"

sudo /usr/bin/python3 \
  /srv/0al/platform/scripts/hosted_managed_production_deploy.py
```

The cloud-init contract installs the distribution `python3` package. These
host-side validation/deployment tools are stdlib-only and are CI-tested on
Python 3.12 and 3.14; the deployment entry point fails closed outside Python
3.12-3.14. Do not create an untracked repository `.venv` solely for host
orchestration. Developer commands and dependency-bearing Platform CLI commands
continue to use the repository virtual environment or the pinned Platform
container image.

Hosts created from an older cloud-init revision may not yet have
`/usr/local/sbin/0al-hosted-managed-checkout`. Bootstrap it once from a trusted
copy of the tracked script, run its `install` command as root, and remove the
temporary copy. Verify the script commit before transfer. Do not replace this
bounded bootstrap with a global Git `safe.directory` exception. New hosts use
the versioned cloud-init installation path and do not need this compatibility
step.

The orchestrator requires the image-lock commit to equal the clean Platform
checkout `HEAD`. Before changing containers it validates the lock, renders and
preflights a candidate environment, requires a drained queue with no workspace
locks, rejects an implicit PostgreSQL image change, validates Compose, and pulls
all digest-pinned images. It atomically installs the environment, recreates the
runtime while preserving the PostgreSQL volume, and waits for the HTTPS
production probe. A failed update restores the previous environment and attempts
to verify the previous runtime. Its public-safe deployment report is written to
`/srv/0al/evidence/hosted-managed-deployment.json`.

This operation does not transfer canary artifacts, enqueue a request, expand the
deployment allowlist, migrate PostgreSQL, create a Git review, or publish a read
model. Initial host bootstrap and database image upgrades remain separate
procedures. Do not retry after an unverified rollback; inspect the deployment
report and container state first.

Validate and start the production control plane. The default profile starts
PostgreSQL, the authenticated service, and TLS ingress. It intentionally does
not start an execution worker:

```bash
make hosted-managed-production-contract
make hosted-managed-production-compose-smoke
docker compose --project-name platform-managed-production \
  --file docker-compose.hosted-managed-production.example.yml config >/dev/null
docker compose --project-name platform-managed-production \
  --file docker-compose.hosted-managed-production.example.yml up --detach

/usr/bin/python3 scripts/hosted_managed_production_probe.py \
  --service-url https://managed.example.org \
  --compose-file "$PWD/docker-compose.hosted-managed-production.example.yml" \
  --env-file /etc/0al/hosted-managed-production.env \
  --project-name platform-managed-production \
  --output /srv/0al/evidence/probe-before-reboot.json
```

The bounded Compose smoke explicitly enables the `continuous-worker` profile
and starts the real Caddy, PostgreSQL, service, and worker with a one-day
self-signed fixture certificate and a temporary local
registry so even the test image is addressed by digest. It enqueues no managed
request and removes containers, registry, and volumes afterward.
Build `Dockerfile.hosted-managed-ingress` from a digest-pinned Caddy base and
publish that image by digest. The build removes Caddy's unused low-port file
capability, allowing the non-root ingress container to keep `cap_drop: ALL` and
`no-new-privileges` while listening on port `8443`.

The production ingress also requires Compose `init: true`. Docker health checks
are executed as short-lived processes inside the container; without a minimal
PID 1 reaper, Caddy can accumulate their zombie children until the container
PID limit prevents further health checks and `docker exec`. Treat a rising
ingress PID count or `procReady not received` health output as a blocking
runtime defect. Recreate the ingress from the validated Compose contract rather
than increasing `pids.max` or disabling health checks.

The default probe requires the three control-plane services to be healthy, the
worker to be absent, PostgreSQL as the queue adapter, and exactly
`review_status_execute` in service health. Use `--worker-mode continuous` only
for a separately approved continuous-worker rollout; that mode additionally
requires the worker service and a fresh heartbeat. The report is public-safe
and omits Compose paths and credentials.

Initial operational targets are diagnostic objectives, not an external SLA:

- alert immediately on any quarantined request or expanded allowlist;
- alert after two failed probes; when continuous mode is explicitly enabled,
  also alert on a worker heartbeat older than 30 seconds;
- alert when a read-only canary does not terminate within its bounded window;
- run a read-only canary at least daily during rollout and after each deploy;
- run strict recovery and queue-drain audit after unclean shutdowns;
- retain private backup reports with the encrypted off-host backup they pin.

### Private backup and restore smoke

Use the bounded production backup-cycle orchestrator as the primary operator
entry point. It probes the runtime, requires a drained queue, stops the public
enqueue boundary, audits the queue again, stops the worker, creates the private
backup, runs an isolated restore smoke, verifies the complete output set, and
then restarts and probes the control plane. A continuous worker is stopped if
present but is not implicitly re-enabled. Once quiescing starts, control-plane
restart is attempted from a `finally` path even when backup or restore
verification fails.

On the production host, from the commit-pinned Platform checkout, run:

```bash
sudo /usr/bin/python3 \
  /srv/0al/platform/scripts/hosted_managed_production_backup_cycle.py \
  --service-url https://managed.example.org

backup_id="$(sudo cat /srv/0al/evidence/current-backup-id.txt)"
sudo cat /srv/0al/evidence/hosted-managed-backup-cycle.json
```

The generated backup remains private under
`/srv/0al/backups/<backup-id>/`. The cycle report and pre-backup probe are
public-safe summaries under `/srv/0al/evidence/`; they are evidence, not the
backup payload. A failed cycle must not be retried until the final runtime probe
passes or the service state has been diagnosed manually.

The lower-level `hosted_managed_runtime_backup.py backup` and `restore-smoke`
commands remain available for diagnostics and tests, but operators should not
manually reproduce the stop/start sequence. `restore-smoke` creates a temporary
PostgreSQL database, restores the versioned queue export, compares every table
count, verifies every archived artifact digest without extracting unsafe paths,
and forcibly removes the temporary database. Neither tool has authority to
restore over production.

#### Encrypted off-host copy

Copy the entire private backup to a different failure domain. From an operator
machine with `ssh` and `age`, stream the remote archive directly into `age`:

```bash
backup_id="$(ssh -o IdentitiesOnly=yes \
  -i "$HOME/.ssh/0al-platform-canary" \
  root@managed.example.org \
  cat /srv/0al/evidence/current-backup-id.txt)"

.venv/bin/python scripts/hosted_managed_offsite_backup.py \
  --backup-id "$backup_id" \
  --ssh-target root@managed.example.org \
  --ssh-identity "$HOME/.ssh/0al-platform-canary" \
  --age-recipient-file "$HOME/.ssh/0al-platform-canary.pub" \
  --output-dir "$HOME/Backups/0AL/Platform" \
  --output "$HOME/Backups/0AL/Platform/$backup_id-export-report.json"
```

The script requires both backup and restore-smoke reports on the host, refuses
unsafe backup ids and existing output files, and writes the encrypted archive
atomically with mode `0600`. The plaintext tar stream exists only in the pipe
from SSH to `age`; no plaintext tar is written to the operator machine. The
public-safe export report contains only the backup id, archive basename, sizes,
and plaintext/encrypted SHA-256 digests. It does not contain the remote host,
local paths, credentials, private key, or backup payload.

The recipient file is public material. The corresponding private SSH key stays
outside the repository and may remain passphrase-protected in the OS keychain or
SSH agent. Platform passes its filename to `ssh`/`age`; it does not read or
publish the private key. Verify that the encrypted archive can be listed without
writing plaintext to disk:

```bash
age --decrypt \
  --identity "$HOME/.ssh/0al-platform-canary" \
  "$HOME/Backups/0AL/Platform/$backup_id.tar.age" |
  tar --list --gzip --file -
```

Do not commit the encrypted payload or its private export report to this public
repository. Keep at least one encrypted copy outside the VPS. Deleting the VPS
before this step leaves no independent recovery copy.

#### Backup retention policy

The versioned policy is
[`backup-retention-policy.json`](../deploy/hosted-managed/backup-retention-policy.json).
Validate it before applying retention decisions:

```bash
make hosted-managed-backup-retention-contract
```

The current canary policy retains:

- at least 3 successful private VPS backups, with a target maximum age of 7
  days;
- at least 7 successful encrypted operator-local backups, with a target maximum
  age of 30 days;
- at least 7 successful encrypted cloud/off-site backups, with a target maximum
  age of 30 days.

A backup becomes a prune candidate only when it is older than the tier's
`maximum_age_days` **and** deleting it would leave at least
`minimum_successful_copies` in that tier. Never prune the backup referenced by
the current production sign-off, the latest verified backup, or the only
remaining recovery copy. A copy is successful only after restore-smoke evidence
and digest verification; a cloud placeholder or an unverified transfer does not
count.

The policy is audit-only: automatic deletion remains disabled. Before manual
deletion, inventory all three tiers, identify the protected backup ids, verify
the second failure-domain copy, and record the selected ids. Delete only those
ids that satisfy both age and count rules. This repository intentionally does
not include a timer or unattended prune command while the production canary is
the only hosted deployment.

### Canary, reboot, replay, and rollback

Host reboot remains an explicit operator-confirmed action rather than part of
the backup script. This prevents a successful backup command from unexpectedly
rebooting production. The reproducible sequence is: complete the bounded backup
cycle and encrypted off-host copy, run a fresh canary, explicitly reboot, then
run strict recovery, the post-reboot probe, and replay the identical canary.
Retain the canonical evidence filenames shown below so the combined sign-off
gate can verify causal order.

Use an open review PR and a workspace-bound, queue-safe
`review_status_execute` request. Run the existing canary through the public TLS
origin with its bearer token file and with host-local artifact access so output
bytes are checked against receipt digests. Copy only the queue request, the
digest-pinned workspace initialization report, and the portable promotion
execution report into the workspace-scoped artifact directory. Do not copy the
whole developer `runs/` directory because it may contain local-only raw input.

The production host does not need a Platform virtual environment. Run the
dependency-bearing canary client from the same digest-pinned Platform image as
the service and worker. The canary container gets no Docker socket, mounts the
service token and request read-only, mounts artifacts read-only, and can write
only its public-safe evidence report:

```bash
set -a
. /etc/0al/hosted-managed-production.env
set +a

docker run --rm \
  --network host \
  --user 1000:1000 \
  --read-only \
  --tmpfs /tmp:rw,nosuid,nodev,noexec,size=16m \
  --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --mount \
    type=bind,src="$PLATFORM_MANAGED_OPERATION_TOKEN_FILE",dst=/run/secrets/managed_operation_token,readonly \
  --mount type=bind,src=/srv/0al/canary,dst=/canary,readonly \
  --mount \
    type=bind,src="$PLATFORM_MANAGED_OPERATION_ARTIFACT_ROOT",dst=/workspace/SpecGraph,readonly \
  --mount type=bind,src=/srv/0al/evidence,dst=/evidence \
  "$PLATFORM_MANAGED_OPERATION_IMAGE" \
  python3 scripts/platform.py managed-operation canary \
    --service-url https://managed.example.org \
    --auth-token-file /run/secrets/managed_operation_token \
    --request /canary/review-status-request.json \
    --artifact-root /workspace/SpecGraph \
    --output /evidence/canary.json \
    --format json
```

Install transferred artifacts with fixed modes, then apply numeric ownership
with `chown 1000:1000`. A hardened host may intentionally have no passwd entry
for runtime UID 1000, in which case `install -o 1000` can interpret `1000` as a
missing user name and fail even though numeric container ownership is correct.

Verify SpecSpace in hosted mode with `specspace product-smoke` and
`--expect-managed-mode hosted_managed_ready`. This expects the SpecSpace
readiness pair `status=hosted_managed_ready` and `mode=hosted_managed`; the
separate `backend_managed_ready` profile is reserved for the local subprocess
executor. Reboot the host, rerun strict
recovery, create `probe-after-reboot.json`, and submit the identical canary
request again as `replay-canary.json`. The replay must preserve request id,
idempotency key, output refs and `attempt=1`.

For Timeweb SpecSpace, publish the dedicated hosted manifest profile only after
the executor token has been configured in the Timeweb deployment environment:

```text
SPECSPACE_HOSTED_MANAGED_EXECUTOR_TOKEN=<same service token stored on the VPS>
```

Do not commit or pass that value through the Platform workflow. The generated
Compose manifest converts it into a file-mounted secret and persists only
SpecSpace-owned queue/request state in a named volume. The Platform workflow
inputs are non-secret:

```text
hosted_managed_execution_enabled=true
hosted_managed_executor_url=https://managed.specgraph.tech
```

The first production UI canary remains bounded. Submit exactly one
`review_status_execute` from the Product Workspace, record the server-issued
request id, and process it with the tracked `bounded-worker` host wrapper.
Success requires `hosted_managed_ready`, `attempt=1`, a digest-pinned review
status report, a drained queue, and a stopped worker. This evidence does not
authorize `continuous-worker` or another operation id.

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
green queue receipt. By default every evidence report must be no older than 24
hours and must follow the documented causal order from preflight through
rollback; `--max-evidence-age` may narrow that window but should not be expanded
to reuse evidence from an earlier deployment:

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

### Recorded production canary status

The initial `hosted-operation-canary` production rollout completed the bounded
`review_status_execute` canary, reboot/recovery replay, digest verification,
queue-drain audit, backup/restore smoke, hosted SpecSpace smoke, read-only
rollback, and final combined sign-off. The original request remained at
`attempt=1`, and the resulting report status was
`production_canary_signed_off`.

The worker was stopped after the bounded rollout. This is the expected steady
state until a separate rollout decision chooses one of the following:

- keep the worker stopped and start it only for bounded maintenance windows;
- keep a read-only worker enabled for monitored `review_status_execute` jobs;
- propose an allowlist expansion with operation-specific recovery, monitoring,
  and rollback evidence.

Do not replay the signed-off request as a new semantic probe. Its idempotency
key must continue to resolve to the existing receipt. A fresh probe requires a
new open review object, validated input evidence, and a new queue-safe request.

### Bounded worker operating policy

`deploy/hosted-managed/worker-window-policy.json` is the versioned,
fail-closed policy for the current production operating mode. It permits only
`review_status_execute`, one exact fresh request, one attempt, and at most 900
seconds. It requires strict recovery, an otherwise empty active queue, no
workspace locks, authoritative output reports, and a stopped worker after the
window. It does not permit arbitrary commands, allowlist expansion, unpinned
requests, irreversible retries, or a persistent worker.

The production Compose profile now has three distinct modes:

- no worker profile: the default steady state;
- `bounded-worker`: a one-shot container started only through the tracked host
  wrapper for one exact request;
- `continuous-worker`: the prior long-running worker, retained for explicit
  compatibility and future rollout decisions but never enabled by default.

It also contains the isolated `promotion-dry-run-window` profile. That profile
is not a fourth steady state. It starts one fixed, non-restarting worker for the
`promotion_execute_dry_run` policy and is accepted only when the service
allowlist contains that operation alone. The continuous worker fails closed if
the deployment is switched to this profile.

Do not run the bounded service with `docker compose up`. After the request has
been authenticated and enqueued while the worker is stopped, record the
server-issued request id and choose a fresh operator window id:

```bash
request_id='managed-operation://<workspace>/review_status_execute/<opaque-id>'
window_id="review-status-$(date -u +%Y%m%dt%H%M%Sz)"

sudo /usr/bin/python3 \
  /srv/0al/platform/scripts/hosted_managed_production_worker_window.py \
  --window-id "$window_id" \
  --request-id "$request_id"
```

The host wrapper performs the complete bounded sequence:

1. validate the exact read-only deployment allowlist and policy;
2. prove that neither bounded nor continuous worker is running;
3. execute fixed `managed-operation recover --strict` through the maintenance
   profile;
4. start one `bounded-worker` container pinned to the exact request id;
5. let the worker revalidate binding/input digests and run only the registered
   Platform wrapper;
6. enforce the policy timeout and force-remove a timed-out container;
7. prove that no worker remains;
8. verify the core report identity, policy digest, terminal state, and
   authoritative output report digests;
9. write immutable public-safe host evidence under
   `/srv/0al/evidence/worker-window-<window-id>.json`.

The worker also writes the core report at
`runs/managed-worker-windows/<window-id>.json`. Queue success alone is not
lifecycle completion; the operation's Platform output reports remain
authoritative. A blocked or timed-out window must not be retried with the same
window id. Inspect its diagnostics and queue state first. A terminal
`attempt=1` success may be reconciled into a fresh window report without
re-executing the operation; any ambiguous or irreversible state remains
fail-closed.

Validate the code and Compose contract before deploying this mode:

```bash
make hosted-managed-production-worker-window-contract
make hosted-managed-production-contract
```

This policy is an operating boundary, not authority to keep the worker running.
Enabling `continuous-worker` or selecting the tracked
`promotion_execute_dry_run` profile in production requires a separate rollout
decision and updated evidence.

### Promotion dry-run bounded profile

`deploy/hosted-managed/promotion-dry-run-worker-window-policy.json` is the
tracked first allowlist-expansion policy. It preserves the same one-request,
attempt-zero, strict-recovery, exclusive-queue, timeout, and stopped-worker
requirements as the read-only policy. It additionally requires these two
authoritative outputs:

```text
runs/product_candidate_promotion_execution_report.json
runs/git_service_promotion_execution_report.json
```

The host wrapper verifies both receipt digests and report semantics. A valid
result must be a strict dry-run: no physical candidate worktree, copied files,
commit, branch, pull request, read-model publication, canonical spec mutation,
or Ontology write. Queue success without both matching reports is blocked.

Before a clean-VM or explicitly approved production window, deploy the same
immutable image lock with the operation-specific profile while the worker is
stopped:

```bash
sudo /usr/bin/python3 \
  /srv/0al/platform/scripts/hosted_managed_production_deploy.py \
  --operation-profile promotion-dry-run

sudo /usr/bin/python3 \
  /srv/0al/platform/scripts/hosted_managed_production_probe.py \
  --service-url https://managed.specgraph.tech \
  --compose-file \
    /srv/0al/platform/docker-compose.hosted-managed-production.example.yml \
  --env-file /etc/0al/hosted-managed-production.env \
  --project-name platform-managed-production \
  --operation-profile promotion-dry-run
```

The hosted image itself must pass the wrapper dependency smoke from
`platform-deploy-bundle`. A successful local `.venv` run is insufficient:
`promotion_execute_dry_run` requires both the PostgreSQL adapter and the JSON
Schema validator inside the immutable worker image.

The managed request must also pin all three promotion inputs:

```text
runs/graph_repository_promotion_request.json
runs/candidate_approval_decision.json
runs/graph_repository_execution_plan.json
```

The promotion request pins the plan digest in `plan_sha256`. Hosted execution
passes the separately transported plan through `--plan`; the wrapper rejects a
missing or mismatched digest instead of following producer-machine absolute
paths from `plan_ref` or `runs_dir`.

Promotion-request generation applies the same portability rule only when an
explicitly selected and validated initialization report identifies the plan's
current directory as the exact `runs/<workspace-id>` location. A compact
binding embedded only in the approval decision cannot authorize relocation.
The run ref must equal `runs/{workspace_id}`, not merely share the `runs/`
prefix. Legacy or unbound plans continue to use their embedded `runs_dir`, and
cross-run approval evidence remains blocking.

Authenticate and enqueue exactly one validated
`promotion_execute_dry_run` request while no worker is running. Record the
server-issued request id, then open one window:

```bash
request_id='managed-operation://<workspace>/promotion_execute_dry_run/<opaque-id>'
window_id="promotion-dry-run-$(date -u +%Y%m%dt%H%M%Sz)"

sudo /usr/bin/python3 \
  /srv/0al/platform/scripts/hosted_managed_production_worker_window.py \
  --operation-profile promotion-dry-run \
  --window-id "$window_id" \
  --request-id "$request_id"
```

Acceptance requires `attempt=1`, a drained queue, no active lock, both
digest-pinned reports, `dry_run_reports_verified: true`, and no candidate
worktree under `.platform/candidates/<workspace>`. Regardless of success, do
not leave the expanded service profile in place. After preserving the reports
and diagnosing any ambiguity, restore the read-only baseline:

```bash
sudo /usr/bin/python3 \
  /srv/0al/platform/scripts/hosted_managed_production_deploy.py \
  --operation-profile review-status

sudo /usr/bin/python3 \
  /srv/0al/platform/scripts/hosted_managed_production_probe.py \
  --service-url https://managed.specgraph.tech \
  --compose-file \
    /srv/0al/platform/docker-compose.hosted-managed-production.example.yml \
  --env-file /etc/0al/hosted-managed-production.env \
  --project-name platform-managed-production \
  --operation-profile review-status
```

Then run the bounded backup cycle and encrypted off-host export. The profile
does not authorize `promotion_review_execute`, a persistent worker, or any
other operation.

### Recorded promotion dry-run clean-VM status

The operation-specific clean-VM gate passed on ARM64 with Platform commit
`f7e3d66aeca1de51d0b4ffccdbeda5f86e97d581` and its digest-pinned hosted image.
The fresh request started at attempt `0`, completed at attempt `1`, pinned both
registered reports, drained the queue and workspace lock, and left Git HEAD,
refs, status, and worktree inventory unchanged. Strict recovery, a non-empty
PostgreSQL backup, report digest verification, worker shutdown, and VM shutdown
also passed.

This evidence authorizes only the next production preflight and one explicit
bounded window. Production must still begin from the stopped-worker read-only
baseline, take a fresh off-host backup, prepare a new production request, and
restore `review_status_execute` immediately after the window.

### Recorded promotion dry-run production bounded status

The single authorized production window completed for the dedicated
`hosted-operation-canary` workspace on Platform commit
`f7e3d66aeca1de51d0b4ffccdbeda5f86e97d581`. Pre-operation backup cycle
`production-20260716t104508z`, isolated restore smoke, encrypted off-host
export, and archive digest verification passed before the allowlist changed.

The service then advertised only `promotion_execute_dry_run`. Request
`managed-operation://hosted-operation-canary/promotion_execute_dry_run/4c0f6638dbe110ea11058591`
started at attempt `0` and bounded window
`promotion-dry-run-20260716t105624z` completed it at attempt `1`. The core and
host reports had no diagnostics, the queue drained, no workspace lock remained,
and the receipt pinned both authoritative outputs:

- product promotion execution:
  `ce0cef5f904cd602bd497efd3443605f82f9584181541de384ce7118c353d562`;
- Git Service promotion execution:
  `747255542d3b0c4aa64c13fcaae42b10a8faab98c3d1038a09599a3e66b2a79b`.

Both reports described a strict dry-run. SpecGraph HEAD, status, and worktree
inventory were unchanged; no candidate worktree, commit, branch, pull request,
read model, canonical spec mutation, or Ontology write was created.

Production was immediately restored to the stopped-worker
`review_status_execute` profile. Strict recovery was a no-op. Post-operation
backup cycle `production-20260716t110028z`, isolated restore smoke, encrypted
off-host export, archive digest verification, and the final production probe
passed. This evidence closes the approved window; it does not authorize a
persistent worker, another dry-run window, or an irreversible operation.

### Recorded bounded worker pilot status

The first post-sign-off bounded worker pilot completed against SpecGraph review
PR `#689`. Production ran Platform commit
`2c7a9cd240d2379a9452f18d57b756295425e21c` with only
`review_status_execute` enabled. The fresh request started at attempt `0`, the
one-shot worker processed it exactly once, and the authoritative review-status
report observed the review as open without merging it or publishing a read
model.

The core and host reports both completed without diagnostics. The core report
recorded attempt `1`, one processed operation, digest-pinned authoritative
output, zero active jobs after execution, and zero active locks. The host report
confirmed that the bounded container exited, the continuous worker remained
disabled, and no worker was left running. The subsequent production backup
cycle `production-20260715t154652z`, isolated restore smoke, encrypted off-host
export, queue-drain audit, and post-operation probe all passed.

This result validates the bounded operating policy for a second fresh read-only
request. It does not authorize a persistent worker or expand the production
allowlist. SpecGraph PR `#689` was subsequently merged through the normal
repository review process as merge commit `588c4d8`. The canary itself did not
merge the review or publish a read model.

### Next hosted rollout phases

The operational-hardening baseline for these phases is now explicit:

- off-host backup export waits for both pipeline processes and reports a failed
  `age` process as `age encryption failed`, even when the early exit also closes
  the input pipe;
- the development/CI Compose profile reserves at least 90 seconds for service
  and worker startup because that profile installs hosted Python dependencies
  inside each container before starting the process;
- immutable runtime and production profiles continue to use prebuilt images and
  do not gain execution authority from this startup allowance.

These checks harden diagnostics and CI startup only. They do not start the
production worker, expand the operation allowlist, or change queue replay
policy.

Proceed from the signed-off baseline in bounded stages:

1. preserve the completed CI timing/error-reporting hardening and keep
   backup/recovery evidence current;
2. use the versioned bounded worker policy for each new read-only pilot until a
   separate operating decision enables a continuously running worker;
3. preserve the completed fresh `review_status_execute` pilot evidence and keep
   the worker stopped between bounded windows;
4. preserve the completed one-shot `promotion_execute_dry_run` production
   evidence and require a new proposal before another bounded window or
   allowlist expansion;
5. expose only the enabled operations through SpecSpace hosted lifecycle UX;
6. propose irreversible Git review or publication operations one at a time.

Each phase must preserve a narrow allowlist, durable authoritative reports,
queue drain, monitoring, recovery, rollback, and a post-operation worker-state
decision. Production canary sign-off is a prerequisite, not blanket authority
for later phases.

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
