# Hosted Bounded Product Operations Rollout Proposal

Status: **production rollout accepted**

Deployment profile: `bounded-product-dry-run`

Enabled operations:

```text
promotion_execute_dry_run
review_status_execute
```

## Product Goal

Let production SpecSpace expose the next two reversible hosted actions without
requiring an operator to redeploy Platform between them:

```text
inspect Git review status
or
validate promotion through a strict Git dry-run
```

SpecSpace may authenticate and enqueue either request. The production worker
remains stopped by default. An operator still opens one operation-specific
bounded window for one exact server-issued request.

## Decision

Add an explicit two-operation deployment profile after both operations have
independently passed local, clean-VM, and production bounded execution.

This is an expansion of request intake and Product Workspace UX, not an
expansion to continuous execution. The deployment allowlist may contain both
registered operations, while every worker window narrows its container
allowlist to exactly one operation and one request:

```text
service allowlist
  promotion_execute_dry_run,review_status_execute

review worker window
  review_status_execute only

promotion dry-run worker window
  promotion_execute_dry_run only
```

`promotion_review_execute`, read-model publication, consume-on-attempt
operations, and arbitrary commands remain disabled.

## Safety Contract

1. The profile is explicit and fail-closed. An unknown, duplicate, reordered
   with extra ids, or irreversible operation blocks preflight.
2. The steady state has no worker container.
3. `continuous-worker` is forbidden for the combined profile.
4. Each bounded worker policy still contains exactly one operation id, requires
   one expected request at attempt `0`, and processes at most one operation.
5. The host wrapper verifies that the selected operation belongs to the
   approved deployment profile, then overrides the worker-container allowlist
   to that operation alone.
6. Strict recovery, an exclusive queue, no active locks, digest-pinned inputs,
   authoritative output reports, stopped-worker verification, and immutable
   images remain mandatory.
7. Promotion dry-run acceptance still requires both digest-pinned reports and
   proof that no worktree, branch, commit, pull request, read model, canonical
   spec mutation, or Ontology write occurred.
8. Queue terminal state remains transport evidence. Platform reports remain
   lifecycle authority.
9. Replay-safe promotion dry-runs write request-scoped reports under
   `runs/managed-promotion-dry-runs/`. They must not replace the canonical
   non-dry-run promotion execution report used by review-status and publication
   lifecycle steps.

## SpecSpace Exposure

The Timeweb external-state profile keeps the review-only client allowlist by
default. The second operation appears only with:

```text
--enable-hosted-managed-external-state
--enable-hosted-managed-promotion-dry-run
```

SpecSpace intersects this client maximum with the operation ids reported by
Platform health. If either side does not advertise an operation, the UI must
not offer it as executable.

The ephemeral Timeweb canary profile cannot use this expansion. Durable
external SpecSpace state is required so request and receipt observability
survives App container replacement.

## Rollout Preconditions

- Platform PR is merged and immutable hosted images are published and pinned.
- Production backup, isolated restore smoke, and encrypted off-host export are
  current.
- Queue is drained; no active lock or worker exists.
- Existing production service and SpecSpace smoke are green.
- The selected workspace has a ready durable binding and current promotion or
  review evidence.
- Timeweb global secrets remain attached; no credential value enters Git.
- The first production request is the only active request in the queue.

Because the bounded policy requires an exclusive queue, operators must not
enqueue review status and promotion dry-run simultaneously. A second active
request blocks the worker window instead of being processed opportunistically.

The first combined-profile production window exposed why the output isolation
is mandatory: a replayed dry-run replaced the canonical non-dry-run promotion
execution report, so the following read-only review-status operation correctly
failed closed. Request-scoped dry-run outputs preserve both the new diagnostic
evidence and the existing Git review provenance.

## Bounded Rollout

1. Deploy Platform with:

   ```bash
   --operation-profile bounded-product-dry-run
   ```

2. Probe with `worker_mode=stopped` and require the exact two-operation health
   allowlist.
3. Publish the Timeweb external-state profile with the explicit promotion
   dry-run opt-in.
4. Run SpecSpace production smoke and confirm both ids appear in
   `hosted_enabled_operation_ids`, with no additional id.
5. From one bound workspace, create exactly one `promotion_execute_dry_run`
   request.
6. Open the existing `promotion-dry-run` worker window for that exact request.
7. Require `attempt=1`, two matching report digests, queue drain, no locks, and
   no Git mutations.
8. Create a fresh `review_status_execute` request only after the queue is
   drained, then use the existing `review-status` window.
9. Re-run Platform probe and SpecSpace smoke with the worker stopped.
10. Take a post-operation backup and encrypted off-host export.

## Recorded Production Acceptance

The production rollout completed on 2026-07-19 UTC against the bound
`hosted-operation-canary` workspace.

- Platform and the persistent Timeweb SpecSpace client exposed exactly
  `promotion_execute_dry_run` and `review_status_execute`.
- UI-originated promotion dry-run window
  `promotion-dry-run-20260719t232321z` completed at `attempt=1`. The queue
  drained and the request-scoped Platform reports were pinned as
  `087b40a5124bef9a7eeca3b8656507dd202de87cbde91b4772a95a59f1877709`
  and
  `6e53df40b53b751563d9081e0f892d853e5b1d29d8e6052f9bea06b1eebb1ff5`.
- The dry-run created no worktree, branch, commit, pull request, read model,
  canonical spec mutation, or Ontology write. The canonical non-dry-run
  promotion report remained separate from the request-scoped diagnostic
  outputs.
- A pre-acceptance review-status inspection exposed a stale restoration of the
  closed duplicate PR `#683`; it was rejected as rollout evidence. The
  canonical promotion report for merged PR `#701` was restored from the
  previously verified production backup.
- The fresh UI-originated review-status window
  `review-status-20260719t232834z` then completed at `attempt=1`, inspected
  merged PR `#701`, drained the queue, and pinned report SHA-256
  `2d145dfc52ecf1c0443741c9c467c84c37efa13bde0ac215d8239bf4b94e4d17`.
- The final production probe reported five healthy services, the exact
  two-operation profile, and `worker_mode=stopped`. Platform's independent
  SpecSpace smoke passed all 17 checks; the Product Workspace remained
  published with all seven lifecycle phases complete.
- Post-operation backup `production-20260719t234024z`, dual-database isolated
  restore smoke, and runtime recovery passed. The encrypted off-host archive
  was written with SHA-256
  `f4b44cfddea8f115de4fb01b839fbe9c21abf623c522169a2378170f22264c4d`.

Platform PR `#191` made the backup cycle preserve and validate the active
deployment profile before backup and after restart. This accepted rollout does
not authorize a continuous worker or any additional operation.

## Rollback

Rollback does not delete queue rows or reports:

1. stop and remove any bounded worker container;
2. quarantine ambiguous execution and run strict recovery;
3. return Platform to `--operation-profile review-status`;
4. publish Timeweb without
   `--enable-hosted-managed-promotion-dry-run`;
5. verify review-only Platform health and SpecSpace readiness;
6. take backup and preserve rollout evidence.

## Acceptance

The rollout is accepted only when:

- Platform health exposes exactly the two approved operations;
- SpecSpace exposes the same two-operation intersection;
- the worker is stopped outside bounded windows;
- both operation-specific windows complete independently at `attempt=1`;
- authoritative reports match receipt digests;
- promotion remains a strict dry-run with zero Git mutations;
- the queue drains after each request;
- final production smoke, backup, restore smoke, and off-host export pass.

This proposal does not authorize a continuous worker or the next operation.
