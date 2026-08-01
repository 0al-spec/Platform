# Hosted Promotion Review Production Rollout Proposal

Status: **proposed; implementation and production enablement are not approved**

Operation: `promotion_review_execute`

## Decision Summary

`promotion_review_execute` is the next product-facing hosted operation to
evaluate after the accepted bounded `promotion_execute_dry_run` and
`review_status_execute` profile. It can create a candidate worktree, branch,
commit, push, and GitHub review pull request. It cannot merge that review or
publish a read model.

The operation already exists in the generic managed-operation registry and
fixed executor. It is deliberately absent from every production deployment
profile and bounded-worker policy. Adding its id to an environment variable is
not an accepted rollout because the current production wrapper does not yet
validate the operation-specific confirmation, predecessor dry-run, repository
identity, Git result, or ambiguous-success recovery semantics.

The decision is to proceed to a separate contract implementation PR. Merging
this proposal does not:

- change `PLATFORM_MANAGED_OPERATION_ALLOWLIST`;
- expose the operation through production SpecSpace;
- start a worker or enqueue a request;
- create a worktree, branch, commit, push, or pull request;
- merge a review or publish a read model;
- mutate canonical specs or Ontology packages;
- authorize a continuous worker or another operation.

## Product Outcome

After the complete rollout, an authenticated operator should be able to move a
ready candidate through this bounded transition:

```text
successful current promotion dry-run
-> explicit operator confirmation
-> one exact hosted promotion-review request
-> stopped-by-default bounded worker window
-> candidate branch + commit + review PR
-> digest-pinned authoritative reports
-> SpecSpace waits for review/merge
```

The browser records intent and confirmation. Platform remains the execution
boundary, Git Service owns repository writes, GitHub owns review state, and the
authoritative Platform reports remain lifecycle evidence.

## Existing Managed-Operation Contract

The registered operation currently declares:

- command: `product-candidate-promotion`, `execute`;
- inputs:
  - `runs/graph_repository_promotion_request.json`;
  - `runs/candidate_approval_decision.json`;
  - `runs/product_candidate_promotion_execution_report.json`;
  - `runs/graph_repository_execution_plan.json`;
- outputs:
  - `runs/product_candidate_promotion_execution_report.json`;
  - `runs/git_service_promotion_execution_report.json`;
- side-effect class: `git_review`;
- timeout: 240 seconds;
- replay policy: `reconcile_before_retry`;
- workspace and operation locks plus `git-review:{workspace_id}`;
- `irreversible: true`;
- `requires_explicit_confirmation: true`.

This registry definition is necessary but not sufficient for production. The
implementation gate below must close the remaining semantic gaps before the
operation enters any deployment profile.

## Mandatory Contract Hardening

### 1. Semantic confirmation

The executor currently proves that confirmation evidence exists and retains its
SHA-256 digest. The implementation must also validate its meaning. A valid
confirmation must be a SpecSpace-owned v1 confirmation for exactly:

- the selected workspace and the server-issued authenticated operator profile;
- `promotion_review_execute`;
- `confirmed: true`;
- the current promotion request, approval decision, and execution plan digests;
- one successful request-scoped promotion dry-run and both of its report
  digests;
- a bounded expiry and one-time-use identity;
- a closed authority boundary with no unknown truthy `may_*` fields.

A generic JSON file, a confirmation for another operation or workspace, a
superseded/expired confirmation, or confirmation whose referenced evidence
changed must quarantine the request before any Git command runs.

The browser must not supply `operator_ref` or invent confirmation identity. The
authenticated SpecSpace backend must issue both, persist confirmation as
revisioned state, and atomically transition it from `ready` to `consumed` with
CAS when Platform accepts the request. Reuse, stale revision, or a second
request against the same confirmation must fail before lease acquisition. The
current single-operator Basic authentication profile is sufficient to identify
the issuer for this bounded rollout; it is not a general multi-user identity
system.

### 2. Current request-scoped dry-run evidence

The predecessor dry-run must come from
`runs/managed-promotion-dry-runs/<request-id>.*`, not from a stale canonical
`runs/product_candidate_promotion_execution_report.json`. Both dry-run reports
must match the receipt-pinned SHA-256 digests and the current promotion request,
approval decision, execution plan, candidate, workspace binding, and candidate
branch.

The dry-run reports must remain strict: no physical worktree, branch, commit,
push, pull request, read model, canonical mutation, or Ontology write. A queue
success status without valid reports is not predecessor evidence.

### 3. Repository and Git review preflight

Before leasing the operation, the bounded host path must prove:

- the workspace binding, repository identity, default branch, expected base
  commit, candidate branch, promotion request, approval decision, and execution
  plan are digest-pinned and mutually consistent;
- the production repository checkout is clean and its normalized remote matches
  the validated binding;
- repository identity plus candidate ref has an exclusive lock, even when two
  workspaces target the same repository;
- the candidate worktree path is workspace-scoped and does not already contain
  ambiguous state;
- approved source files are immutable snapshots with matching digests and no
  symlink escape;
- the Git index is clean before staging and the staged diff contains exactly the
  approved files;
- Git hooks and ambient credential helpers are disabled for the operation;
- the GitHub credential is available through the existing secret file, has only
  the required repository contents and pull-request permissions, and is not
  exposed to repository-controlled hooks;
- the exact request is at attempt `0`, the queue is exclusive, no active locks
  exist, and strict recovery has no unresolved lease.

The implementation must extend the request contract rather than leave these as
prose-only checks. The trusted Git Service operation contract, deployment
profile, normalized provider repository, expected base commit, normalized
remote identity, and candidate ref must be explicit digest-pinned inputs. The
fixed executor must pass their validated values through fixed flags such as
`--contract`, `--deployment-profile`, and `--repo`; repository-local defaults
are forbidden for hosted real-review execution.

The queue contract must also gain a deterministic repository-plus-candidate-ref
lock scope derived from those validated inputs. Expanding only
`{workspace_id}` and `{operation_id}` is insufficient. A cross-workspace test
must prove that two requests targeting the same repository and candidate ref
cannot lease concurrently.

No browser-provided argv, repository path, remote URL, branch name, environment,
or output path may reach the worker command.

### 4. Immutable authoritative reports

Real promotion outputs must become request-scoped, immutable, and exclusively
created. A later request must not overwrite
`runs/product_candidate_promotion_execution_report.json` or
`runs/git_service_promotion_execution_report.json`. Any stable lifecycle alias
must be a separately validated projection of a request-scoped report, not the
authoritative mutable file.

Success requires exactly two receipt-pinned output reports. Their content must
prove:

- `dry_run: false` and `open_review_dry_run: false`;
- a physical workspace-scoped candidate worktree was prepared;
- the expected candidate branch was created and pushed;
- an expected non-empty set of approved files was committed;
- the commit SHA is valid and matches the provider-side review head;
- exactly one review PR was opened against the expected repository and base
  branch;
- the review URL and PR number are mutually consistent and the PR is open;
- no merge or read-model publication occurred;
- no canonical spec mutation outside the review branch occurred;
- no Ontology package or term was written or accepted.

Queue completion alone is transport evidence. Any missing report, digest drift,
foreign review identity, partial Git sequence, or expanded authority blocks the
host window.

### 5. Reconciliation, leases, and replay

Delivery remains at-least-once. `reconcile_before_retry` must never become an
automatic retry policy.

- The worker must keep a fenced lease alive while the irreversible subprocess
  is running; an expired lease must not permit a second worker to start.
- A completed matching pair of authoritative reports may be reconciled without
  running Git commands again.
- Provider-side repository, branch, commit, and PR state must be reconciled when
  a push or PR may have succeeded without a complete local report pair.
- A timeout or expired lease with no complete matching evidence must be
  quarantined.
- A new confirmation must not bypass unresolved ambiguous state.
- Duplicate review creation, attempt `2`, and blind retry are rollout failures.

The implementation must test the boundary where the PR is created but the
worker loses its lease or exits before queue acknowledgement. Cleanup after an
ambiguous result is an explicit human decision; the worker must not force-push,
delete a branch, or close a PR automatically.

## Operation-Specific Production Policy

The implementation PR must add a dedicated, versioned bounded-worker policy and
Compose service scoped to exactly `promotion_review_execute`:

- one server-issued expected request id;
- one operation processed;
- maximum initial attempt `0`;
- exclusive queue and strict recovery preflight;
- operation-specific confirmation and report validation;
- maximum bounded duration;
- no continuous worker;
- worker stopped after the window;
- no retry of irreversible operations;
- no arbitrary command, path, environment, or allowlist expansion.

The first clean-VM and production exercises should use a one-operation service
allowlist. A later combined Product Workspace profile may add the operation to
the accepted dry-run/review-status client maximum only after the isolated
operation passes. That combined profile is a separate recorded decision.

No production request may be enqueued until a separate, immutable
`platform_hosted_promotion_review_rollout_authorization` v1 artifact records the
approved workspace, request id, repository, candidate branch, expected base
commit, confirmation digest, predecessor dry-run digests, image-lock digest,
expiry, and single-window scope. The production host wrapper must require this
artifact by absolute path, validate it before provider contact, and record its
SHA-256 digest in host evidence. Proposal merge, implementation merge, and
clean-VM success are not substitutes for this explicit production decision.

The authorization must be issuer-authenticated, not merely hashed. Its
canonical payload must carry an issuer id and detached signature verified
against a public key/fingerprint pinned in root-owned host configuration. The
signature must bind the Platform operation contract, deployment profile,
image-lock digest, provider repository, expected base commit, candidate branch,
request id, confirmation digest, dry-run report digests, window id, issue time,
and expiry. The authorization and signature files must be absolute regular
non-symlink files, owned by the configured host administrator, not group/world
writable, and outside the worker-writable artifact and SpecSpace state roots.
The private signing key must not be present in the worker, service, repository,
container image, or GitHub Actions environment.

## Test Matrix

The implementation gate must include:

1. confirmation kind, workspace, operation, truth value, expiry, one-time-use
   identity, authority, and digest validation;
2. request-scoped dry-run selection and stale/cross-workspace report rejection;
3. repository/remote/base-commit pinning and repository-plus-ref locks;
4. exact request attempt `0 -> 1`, exclusive queue, lease fencing, and lock
   release;
5. fixed command construction with no dry-run flags, hooks, or ambient Git
   credentials;
6. local Git repository execution with a fake GitHub CLI and no production
   contact;
7. successful worktree, exact staged diff, commit, push, PR URL/number, provider
   state, and report digest checks;
8. wrong branch, wrong remote, changed plan, symlink source, dirty index, missing
   report, partial report, report overwrite, and authority-expansion rejection;
9. timeout, expired lease, post-push/pre-PR failure, post-PR/pre-ack failure,
   reconciliation, and quarantine coverage;
10. dedicated Compose profile, stopped-worker enforcement, deployment
    preflight, probe, backup, and rollback tests;
11. PostgreSQL queue parity and a clean-VM bounded exercise.

## Rollout Phases

1. **Proposal:** merge this document without changing production authority.
2. **Contract implementation:** add semantic confirmation, current dry-run
   evidence, repository pinning, immutable reports, lease fencing, result
   validation, reconciliation, and operation-specific policy.
3. **Local integration:** run HTTP -> PostgreSQL -> worker -> local Git service
   with a fake GitHub CLI.
4. **Clean VM:** use immutable images, an isolated test repository, one fresh
   request, backup, strict recovery, and worker shutdown.
5. **SpecSpace staging exposure:** add an explicit non-production opt-in only
   after the isolated Platform gate passes; keep authentication and the
   deployment intersection fail-closed.
6. **Production authorization:** review local and clean-VM evidence, then issue
   the immutable bounded rollout authorization artifact. Without it, do not
   expose the operation, enqueue a request, or contact the provider.
7. **Production preflight:** take a fresh backup and off-host encrypted export,
   prove queue drain, validate non-executing candidate/request artifacts, and
   keep the worker stopped.
8. **Single bounded window:** process one exact request at attempt `1`, validate
   both reports and the provider-side GitHub review, drain the queue, and stop
   the worker.
9. **Immediate post-operation audit:** inspect review status, run authenticated
   SpecSpace production smoke, backup/restore smoke, and post-operation probe.
10. **Persistent-profile decision:** separately decide whether the operation
    may enter a persistent stopped-worker client allowlist. Do not authorize
    continuous execution or read-model publication automatically.

## Rollback

Rollback preserves Git and queue evidence:

1. stop and remove the bounded worker;
2. quarantine any ambiguous request and retain its events and reports;
3. restore the accepted `bounded-product-dry-run` or `review-status` deployment
   profile;
4. remove `promotion_review_execute` from the SpecSpace client maximum;
5. run production probe and authenticated/anonymous SpecSpace smoke;
6. take backup, isolated restore smoke, and encrypted off-host export;
7. leave any already-opened review PR open for explicit human close or merge.

Rollback must not delete a branch, force-push, close a PR, delete queue rows, or
overwrite authoritative reports automatically.

## Acceptance

The proposal selects `promotion_review_execute` for implementation, subject to
all gates above. It does not approve production enablement. A future production
window requires an explicit rollout decision after local and clean-VM evidence
is reviewed.

The implementation PR must make acceptance machine-checkable. At minimum it
must define and validate:

- `platform_hosted_promotion_review_confirmation` v1;
- `platform_hosted_promotion_review_rollout_authorization` v1;
- request-scoped `platform_product_candidate_promotion_execution_report` and
  `platform_git_service_promotion_execution_report` artifacts;
- `platform_hosted_promotion_review_reconciliation_report` v1;
- the existing `platform_hosted_managed_worker_window_report` and
  `platform_hosted_managed_production_worker_window_report` with the new
  operation profile.

The focused validation command must cover confirmation consumption, exact
request construction, repository/ref locking, report schemas, provider-state
reconciliation, timeout/quarantine, and host rollback. The full release gate
remains `make python-quality`; clean-VM and production evidence are additional
rollout gates rather than replacements for local tests.

The proposal PR itself intentionally contains no implementation of those future
gates. Its executable regression scope is narrower: it must prove that
`promotion_review_execute` remains absent from production operation profiles,
deployment profiles, policy files, and Compose worker services until the
contract implementation lands with its own behavioral tests.
