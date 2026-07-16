# Hosted Promotion Dry-Run Production Rollout Proposal

Status: **bounded policy implemented; clean-VM and production rollout evidence pending**

Operation: `promotion_execute_dry_run`

## Decision Summary

`promotion_execute_dry_run` is the preferred first expansion of the hosted
production operation allowlist because the registered Platform operation is
explicitly dry-run-only and produces durable evidence without opening a Git
review. The operation-specific bounded policy is implemented, but production
enablement still requires the clean-VM drill and an explicit rollout decision.

The default production profile still accepts only `review_status_execute`.
Tracked operation profiles now let the deploy, preflight, probe, Compose, and
bounded worker wrappers switch atomically to exactly
`promotion_execute_dry_run` for one stopped-worker window. A mixed allowlist or
continuous dry-run worker remains invalid.

Merging this proposal does not:

- change `PLATFORM_MANAGED_OPERATION_ALLOWLIST`;
- start a worker;
- enqueue a managed request;
- permit a persistent worker;
- create a Git worktree, commit, branch, or pull request;
- publish a read model;
- mutate canonical specs or Ontology packages.

## Why This Operation Is First

The managed-operation registry already constrains the operation to:

- command family: `product-candidate-promotion`, `execute`, `--dry-run`, and
  `--open-review-dry-run`;
- input refs: `runs/graph_repository_promotion_request.json`,
  `runs/candidate_approval_decision.json`, and the separately digest-pinned
  `runs/graph_repository_execution_plan.json`;
- output refs: `runs/product_candidate_promotion_execution_report.json` and
  `runs/git_service_promotion_execution_report.json`;
- side-effect class: `git_dry_run`;
- replay policy: `same_request_dry_run_only`;
- timeout: 120 seconds;
- `dry_run_only: true`.

This is narrower than `promotion_review_execute`, which can create real Git
review state and therefore remains out of scope. It is more useful than another
read-only status inspection because it validates the next execution boundary:
promotion planning and Git Service dry-run behavior for one bound workspace.

## Preconditions

All conditions below are mandatory before a production rollout PR may enable
the operation:

1. The existing production canary sign-off remains valid and strict recovery,
   backup, restore smoke, and post-operation probes are green.
2. The worker is stopped and the queue has no active jobs or workspace locks.
3. A dedicated workspace has a valid durable binding, approval decision, and
   promotion request with matching identity and input digests.
4. The same request passes the local HTTP/queue/worker integration and a clean
   VM or staging bounded-window exercise.
5. Service and worker use the same explicit deployment allowlist and immutable
   image lock.
6. A fresh off-host encrypted backup exists before the production window.
7. The production request begins at attempt `0` and is the only request eligible
   for the bounded window.

## Implemented Bounded Contract

The implementation keeps the existing read-only production policy as the
default and adds a separate dry-run policy without generalizing the worker into
an arbitrary operation runner.

Implemented controls:

1. Add a versioned bounded-worker policy scoped to exactly
   `promotion_execute_dry_run`, one expected request, one processed operation,
   and a stopped worker after the window.
2. Make the host wrapper select an explicit tracked policy and validate that the
   deployment allowlist exactly matches that policy.
3. Extend preflight, runtime probe, Compose validation, and host evidence for the
   dry-run profile without weakening the existing `review_status_execute`
   checks.
4. Verify both authoritative output reports by logical ref and SHA-256 digest.
5. Verify operation semantics from report content, not only file presence or a
   successful queue receipt.
6. Add negative tests for expanded allowlists, stale or missing output reports,
   `dry_run != true`, attempted Git mutation, timeout, and ambiguous lease
   recovery. Foreign workspace inputs and stale input digests remain guarded by
   the hosted executor contract before Platform execution.
7. Keep `promotion_review_execute`, publication, and consume-on-attempt
   operations disabled.

The production allowlist should contain only `promotion_execute_dry_run` during
the one-operation window. Running both canary operations concurrently is not
needed for this evaluation and would make queue exclusivity less clear. After
the window, restore the normal stopped-worker configuration with
`review_status_execute` as the only service-advertised operation unless a later
operating decision says otherwise.

## Success Evidence

The bounded production window succeeds only when all of the following are true:

- queue terminal state is `succeeded` at `attempt=1`;
- queue is drained and no workspace lock remains;
- bounded and continuous worker containers are stopped;
- core and host window reports are ready and have no diagnostics;
- both registered Platform reports exist and match the receipt digests;
- product promotion execution reports `dry_run: true`;
- Git Service reports dry-run/open-review-dry-run behavior only;
- no physical Git worktree exists;
- no branch, commit, or pull request was created;
- no read model was published;
- strict recovery, backup/restore smoke, off-host export, and the
  post-operation probe pass.

Queue success alone is not acceptance. Authoritative Platform reports and their
content determine lifecycle completion.

## Recovery And Replay

Delivery remains at-least-once. The operation's
`same_request_dry_run_only` policy permits reconciliation of matching dry-run
evidence but does not justify blind re-execution.

- If the queue is terminal and both output digests match, reconcile evidence;
  do not enqueue a duplicate semantic request.
- If the worker lease expires before authoritative reports exist, run strict
  recovery and inspect queue events before deciding whether a fresh operator
  request is allowed.
- If only one output report exists, or report identity/digests disagree,
  quarantine the request and stop the rollout.
- A timeout must force-remove the bounded worker and leave the operation
  disabled pending diagnosis.
- Any evidence of a real Git mutation is an incident and blocks further
  allowlist expansion.

## Rollback

Rollback is operationally simple because no durable Git side effect is expected:

1. stop and remove the bounded worker;
2. prove the queue is drained or quarantine the ambiguous request;
3. restore the deployment allowlist to `review_status_execute`;
4. run the read-only production preflight and post-operation probe;
5. take a bounded backup and encrypted off-host export;
6. record the result in the hosted operations runbook.

Do not delete queue rows or authoritative reports during rollback. They are the
audit trail needed to distinguish a failed transport from a completed dry-run.

## Rollout Phases

1. **Contract implementation:** complete. The operation-specific policy,
   profile registry, wrapper validation, tests, and docs are tracked.
2. **Local and CI validation:** run the real HTTP handler, PostgreSQL queue,
   worker, and report checks with fixture-owned artifacts.
3. **Clean VM or staging drill:** exercise one request with immutable images,
   strict recovery, backup, and worker shutdown.
4. **Production preflight:** prepare one dedicated request and a fresh backup;
   keep the worker stopped.
5. **Single bounded production window:** enable only
   `promotion_execute_dry_run`, process the exact request once, and collect all
   success evidence.
6. **Immediate rollback to baseline:** stop the worker and restore the read-only
   service allowlist.
7. **Post-rollout decision:** decide separately whether the operation may remain
   available for future bounded windows. This proposal does not authorize a
   continuous worker or the next allowlist expansion.

## Approval Gate

The proposal recommends `promotion_execute_dry_run` as the first production
allowlist expansion. The current decision is **proceed to local and clean-VM
validation, not enable production yet**. A separate decision after that evidence
must authorize the single production bounded window.

### Clean-VM runtime dependency finding

The first clean-VM attempt reached the digest-pinned hosted image but stopped
before operation execution because the image contained the PostgreSQL queue
adapter and not the `jsonschema` runtime dependency required by the fixed
product-promotion wrapper. The queue failed closed at `attempt=1`; no output
reports or Git mutations were produced, and that request is not eligible for a
blind retry.

`requirements-hosted.txt` now carries both queue and wrapper validation
dependencies. CI imports `jsonschema` and `psycopg` from the built hosted image
so a source checkout with broader development dependencies cannot mask this
class of deployment defect. A fresh image lock and a fresh clean-VM request are
required before recording the rollout decision.

### Clean-VM portable plan finding

The next fresh request reached the fixed wrapper but failed before Git Service
execution because `promotion_request.plan_ref` and the plan's `runs_dir` still
identified the machine that produced the artifacts. The queue again failed
closed at `attempt=1`, produced no authoritative outputs, drained its lock, and
did not mutate Git. That request is also retained as failure evidence and is not
eligible for a blind retry.

Hosted promotion requests now pin `graph_repository_execution_plan.json` as a
separate managed input. The fixed executor passes it through the portable
`--plan` override, and both product promotion and Git Service verify its digest
against `promotion_request.plan_sha256`. The current workspace-scoped location
of that pinned plan supplies the effective runs directory; stale absolute
producer paths no longer become cross-host execution dependencies.

The following clean-VM request-generation preflight exposed the same host-path
assumption one step earlier: approval source refs were checked against the
plan's embedded `runs_dir` even though the validated binding and transported
plan both identified the current `runs/<workspace-id>` directory. Promotion
request generation now accepts that current directory only when it exactly
matches an explicitly selected, validated initialization report. A compact
binding copied into an approval decision is insufficient on its own. Unbound
plans retain legacy behavior, and a plan paired with approval evidence from
another run remains rejected.
