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
