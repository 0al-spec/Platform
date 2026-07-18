# External SpecSpace State Service

Status: producer and consumer contracts are merged. Production rollout remains
disabled until the dedicated PostgreSQL service, migration, restart
persistence, backup/restore, and deployment sign-off are complete.

## Purpose

The service persists SpecSpace-owned mutable Product Workspace state outside a
replaceable application container:

```text
browser
  -> SpecSpace API
  -> authenticated state service
  -> dedicated PostgreSQL database and role
  -> workspace-scoped private mirror for Platform worker inputs
```

The browser never receives the service URL, bearer token, PostgreSQL endpoint,
or database credentials. SpecSpace remains the only browser-facing state API.
Platform authoritative execution reports remain the only evidence that a
managed operation completed.

## Production Topology

The single-node production profile exposes the state service only through the
existing TLS ingress:

```text
https://managed.specgraph.tech/specspace-state/v1/health
https://managed.specgraph.tech/specspace-state/v1/specspace-state/*
```

Caddy strips `/specspace-state` before forwarding to the internal service on
port `8092`. The service has no direct public port. It uses a PostgreSQL
service, database, role, password, bearer token, and persistent volume that are
independent from the managed-operation queue.

The state service is the only container with a read-write mount of the private
worker mirror. Managed-operation service and worker mounts are read-only. A
stopped worker and the exact `review_status_execute` allowlist remain the
initial rollout profile.

## Storage Boundary

Production must use a database and least-privileged role that are separate from
the managed-operation queue. A second PostgreSQL service is the default
single-node profile because it makes accidental cross-schema grants impossible.
A separately administered database/role in one PostgreSQL cluster is also
acceptable if grants prove the same isolation.

Each current record is keyed by:

```text
(workspace_id, record_key)
```

Each mutation requires:

- the expected current revision (`0` for create);
- a unique idempotency key;
- one of `active`, `consumed`, `superseded`, or `deleted`;
- canonical JSON object content and its optional SHA-256 assertion.

The service calculates the canonical content digest, increments the revision
under compare-and-swap, and records an immutable version row. Reusing an
idempotency key with another workspace, key, lifecycle state, or content digest
is rejected.

## HTTP Contract

The health route is public and contains no record content:

```text
GET /v1/health
```

All state routes require `Authorization: Bearer <token>`:

```text
GET    /v1/specspace-state/record
GET    /v1/specspace-state/records
GET    /v1/specspace-state/history
GET    /v1/specspace-state/export
PUT    /v1/specspace-state/record
DELETE /v1/specspace-state/record
```

The service accepts only the known SpecSpace state filenames plus bounded
workspace-matching confirmation refs. It rejects absolute paths, `..`, control
characters, unknown files, cross-workspace confirmation paths, oversized
payloads, unknown fields, and stale revisions.

State error responses never echo submitted content.

## Worker Mirror

Successful writes atomically materialize a private derived mirror:

```text
<mirror-root>/<workspace-id>/<record-key>
```

The PostgreSQL record is authoritative; the mirror exists only so the existing
Platform worker can digest-pin and pass `specspace-state://` inputs to fixed
wrappers. The managed-operation resolver prefers this workspace-scoped path and
falls back to the legacy unscoped state file only for local/read-only migration
compatibility.

The state service is the only runtime component allowed to write the mirror.
Managed-operation service and worker mounts remain read-only.

## Local Contract Check

```bash
make specspace-state-contract

.venv/bin/python scripts/platform.py specspace-state init \
  --state-adapter sqlite \
  --database /tmp/specspace-state.sqlite3

PLATFORM_SPECSPACE_STATE_TOKEN='<at-least-32-characters>' \
.venv/bin/python scripts/platform.py specspace-state serve \
  --state-adapter sqlite \
  --database /tmp/specspace-state.sqlite3 \
  --mirror-root /tmp/specspace-state-mirror \
  --host 127.0.0.1 \
  --port 8092
```

PostgreSQL integration uses the existing test database:

```bash
PLATFORM_TEST_POSTGRES_URL='postgresql://...' \
make specspace-state-postgres-integration
```

## Export, Migration, And Retention

Write a private mode-`0600` export:

```bash
.venv/bin/python scripts/platform.py specspace-state export \
  --state-adapter postgresql \
  --database-url-file /run/secrets/specspace_state_database_url \
  --output /private-backups/specspace-state.json
```

Import is create-only by default. `--replace` performs a new CAS revision and
must be used only after explicit review:

```bash
.venv/bin/python scripts/platform.py specspace-state import \
  --state-adapter postgresql \
  --database-url-file /run/secrets/specspace_state_database_url \
  --input /private-backups/specspace-state.json
```

Bound version history without deleting current records:

```bash
.venv/bin/python scripts/platform.py specspace-state prune \
  --state-adapter postgresql \
  --database-url-file /run/secrets/specspace_state_database_url \
  --retain-latest 20
```

The production backup cycle exports both isolated databases:

```text
managed-operations.json
specspace-state.json
workspace-artifacts.tar.gz
```

Restore smoke creates one temporary database in each PostgreSQL service,
restores both versioned exports, verifies row counts and artifact digests, and
removes both temporary databases. The resulting archive is encrypted before
off-host export. State export/import remains the migration and inspection
contract; infrastructure snapshots may supplement but do not replace this
portable restore evidence.

## Authority Boundary

The state service may persist private SpecSpace state. It may not:

- execute managed operations or Platform wrappers;
- mutate SpecGraph artifacts or canonical specs;
- write or accept Ontology terms;
- create branches, commits, or pull requests;
- publish read models;
- treat state persistence as lifecycle completion.

The SpecSpace HTTP adapter and file-state migration contract are merged.
Production managed mode remains off until deployment, migration verification,
restart persistence, restore/concurrency/replay evidence, and rollback are
captured against the production host.
