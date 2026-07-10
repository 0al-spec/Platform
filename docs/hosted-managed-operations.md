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
