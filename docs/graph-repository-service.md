# Graph Repository Service Contract

The Graph Repository Service is the managed write boundary between SpecSpace UI
and a Git-backed SpecGraph workspace.

SpecSpace must not mutate a local checkout directly in production. It should
send authoring and promotion intent to a repository service that owns candidate
workspace allocation, validation gates, branch/commit creation, review opening,
and public-safe read-model publication.

In production this boundary should be implemented as a Git Service, not as
"run `git init` in an arbitrary local folder". The service owns repository
binding, credentials, isolated worktrees, refs, commits, review requests,
concurrency control, audit reports, and read-model publication. Local CLI
commands are the MVP adapter for the same authority model, not the long-term
storage model.

## Current Slice

This repository currently defines the contract shape, example artifact, and
local validator:

- schema: `schemas/graph-repository-service-contract.schema.json`;
- example: `graph-repository-service.example.json`;
- CLI: `scripts/platform.py graph-repository validate`;
- report-only execution plan: `scripts/platform.py graph-repository plan`.

The validator is intentionally stricter than ordinary JSON parsing. It checks
the schema and report-only authority rules:

- no canonical spec mutation without review;
- no Ontology package writes;
- no candidate acceptance without gates;
- no merge without policy;
- no private artifact publication;
- `promotion_policy.auto_merge_allowed` remains false in the MVP.

## Minimal Flow

```text
SpecSpace UI
  -> Graph Repository Service
  -> create_candidate_workspace
  -> validate_candidate_graph
  -> prepare_branch
  -> create_commit
  -> open_review
  -> publish_read_model
```

The first implementation can be a local CLI/service wrapper around Git
worktrees and `make publish-bundle`. Hosted production can later replace the
storage backend with a managed Git provider or queue-backed worker without
changing the UI authority model.

## Git Service Responsibilities

The Git Service is the durable versioning and review subsystem for graph
changes. It must provide stable operations for:

- repository binding and default-branch discovery;
- candidate workspace allocation with isolated worktrees or equivalent storage;
- branch and ref naming under repository policy;
- explicit-path staging and candidate commits;
- review creation and review-status polling;
- merge-status observation without automatic acceptance in the MVP;
- public-safe read-model publication after a merged review;
- audit reports for every operation that crosses the write boundary.

The service must not treat working directories as authority. Authority comes
from validated promotion artifacts, repository policy, review state, and the
published read-model manifest.

The production-facing operation contract lives in
`git-service-operation-contract.example.json` and is validated with:

```bash
scripts/platform.py git-service validate-contract \
  --contract git-service-operation-contract.example.json
```

The request/response envelopes are validated separately:

```bash
scripts/platform.py git-service validate-request \
  --request path/to/git-service-request.json
scripts/platform.py git-service validate-response \
  --response path/to/git-service-response.json
```

For `prepare_worktree`, the request envelope must include input refs for the
promotion request, execution plan, and `candidate_approval_decision`. The
envelope validator checks that the approval ref exists; the approval decision
content is validated by `execute-promotion` before any Git Service operation
runs.

The contract requires these service-level operations:

- `prepare_worktree`;
- `commit_candidate`;
- `open_review`;
- `review_status`;
- `publish_read_model`.

Each operation declares an idempotency scope, required lock scopes, adapter
command, request/response artifact kinds, and write boundary. The existing
`graph-repository` commands remain the local MVP adapter for those operations.

The first orchestration command consumes the report-only promotion request and
runs the local adapter sequence under the Git Service boundary:

```bash
scripts/platform.py git-service execute-promotion \
  --contract git-service-operation-contract.example.json \
  --deployment-profile deployment-profile.product-idea-to-spec.example.json \
  --promotion-request runs/graph_repository_promotion_request.json \
  --approval-decision runs/candidate_approval_decision.json \
  --repository-dir ../SpecGraph \
  --workspace-dir .platform/candidates/my-idea-v1-worktree \
  --materialized-source-dir runs/materialized-candidates
```

`execute-promotion` first validates the promotion request and the explicit
`candidate_approval_decision` against the active deployment profile. The
approval decision must be `approved`, ready, bound to the same candidate,
workflow lane, repository role, and promotion paths. The default profile is
`deployment-profile.product-idea-to-spec.example.json`; it requires:

- `workflow_lane: product_idea_to_spec`;
- `deployment_profile_id: product_idea_to_spec_workbench`;
- `target_repository_role: product_spec_workspace`;
- `authority_profile: workspace_owner_controlled`.

The internal bootstrap profile
`deployment-profile.specgraph-bootstrap-internal.example.json` exists for
maintainer work, but its Git Service mode is `dry_run_only`. That keeps
SpecGraph self-evolution and product idea-to-spec promotion as separate lanes.

After the profile gate passes, `execute-promotion` calls:

1. `graph-repository prepare-worktree`;
2. `graph-repository commit-worktree`;
3. `graph-repository open-review`.

The command writes `platform_git_service_promotion_execution_report`. It does
not merge reviews, accept specs, write Ontology packages, or publish private
artifacts. Use `--open-review-dry-run` when the operator wants to validate the
handoff without pushing a branch or creating a pull request.

After a review exists, the post-review lifecycle is handled by a separate Git
Service finalization command:

```bash
scripts/platform.py git-service finalize-promotion \
  --contract git-service-operation-contract.example.json \
  --open-review-report .platform/candidates/my-idea-v1-worktree/.platform/graph_repository_open_review_report.json \
  --worktree-dir .platform/candidates/my-idea-v1-worktree \
  --bundle-dir ../SpecGraph/dist/specgraph-public \
  --output-dir dist/specgraph-public
```

`finalize-promotion` calls:

1. `graph-repository review-status`;
2. `graph-repository publish-read-model`, only when review state is `merged`.

The command writes `platform_git_service_promotion_finalization_report` so
SpecSpace and operators can inspect the post-review step as part of the same
promotion lifecycle. It does not merge reviews, auto-accept specs, write
Ontology packages, or publish read models from an unmerged review.

## Validate

```bash
scripts/platform.py graph-repository validate \
  --contract graph-repository-service.example.json
```

Use JSON output for CI:

```bash
scripts/platform.py graph-repository validate \
  --contract graph-repository-service.example.json \
  --format json
```

## Plan

Build a local report-only execution plan from SpecGraph run artifacts:

```bash
scripts/platform.py graph-repository plan \
  --contract graph-repository-service.example.json \
  --runs-dir ../SpecGraph/runs \
  --output runs/graph_repository_execution_plan.json
```

The planner requires these SpecGraph artifacts:

- `idea_event_storming_intake.json`;
- `candidate_spec_graph.json`;
- `pre_sib_coherence_report.json`;
- `candidate_repair_loop_report.json`;
- `idea_to_spec_clarification_requests.json`;
- `idea_to_spec_clarification_answers.json`;
- `product_ontology_gap_review_decisions.json`;
- `idea_to_spec_answer_rerun_input.json`;
- `idea_to_spec_rerun_preview.json`;
- `idea_to_spec_rerun_materialization.json`.

The clarification request artifact is retained as review evidence even when its
own readiness state still says `clarification_required`; the accepted answers,
typed ontology decisions, rerun input, rerun preview, and rerun materialization
must be ready before branch preparation. If the rerun preview or materialized
candidate preview still reports unresolved ontology gaps, the plan remains
`ready_for_branch: false`.

Each artifact must remain review-only:

- `canonical_mutations_allowed: false`;
- `tracked_artifacts_written: false`.

The planner does not run Git, create commits, open pull requests, publish read
models, write Ontology packages, or mutate canonical SpecGraph specs. It only
reports whether the read-only inputs are ready for the later repository service
executor.

## Prepare Local

Prepare a local candidate workspace from a ready execution plan:

```bash
scripts/platform.py graph-repository prepare-local \
  --plan runs/graph_repository_execution_plan.json \
  --candidate-id my-idea-v1 \
  --workspace-dir .platform/candidates/my-idea-v1
```

`prepare-local` validates that the plan is `ok`, `ready_for_branch`, and still
within the report-only authority boundary. It writes only local candidate
metadata:

- `candidate_workspace_manifest.json`;
- `graph_repository_local_prepare_report.json`.

It does not execute the planned Git commands. The report includes the branch
name and planned commands so the next executor slice can replace this local
metadata step with controlled worktree creation.

## Promotion Request

Build a report-only handoff artifact when SpecSpace or another operator surface
asks to promote a candidate graph into review:

```bash
scripts/platform.py graph-repository promotion-request \
  --plan runs/graph_repository_execution_plan.json \
  --candidate-id my-idea-v1 \
  --path specs/nodes/SG-SPEC-CANDIDATE.yaml \
  --title "Add candidate spec graph" \
  --body "Review candidate spec graph produced from the idea-to-spec flow." \
  --output runs/graph_repository_promotion_request.json
```

`promotion-request` validates the execution plan, candidate id, review metadata,
and materialized candidate paths before any executor step runs. Paths must stay
inside the future worktree and under `specs/`, `docs/proposals/`, or `runs/`.

The generated `platform_graph_repository_promotion_request` remains report-only:
it does not execute Git commands, create commits, open pull requests, merge
branches, publish read models, accept specs, or write Ontology packages. It is
the stable boundary a future SpecSpace promotion UI can inspect before handing
control to `prepare-worktree`, `commit-worktree`, and `open-review`. It also
declares the workflow lane, deployment profile id, target repository role, and
authority profile so Git Service can reject bootstrap/internal requests in a
product deployment.

## Prepare Worktree

Create the local Git worktree once the execution plan is ready:

```bash
scripts/platform.py graph-repository prepare-worktree \
  --plan runs/graph_repository_execution_plan.json \
  --repository-dir ../SpecGraph \
  --candidate-id my-idea-v1 \
  --workspace-dir .platform/candidates/my-idea-v1-worktree
```

`prepare-worktree` executes only the bounded Git preparation commands:

- `git fetch origin <default_branch>`;
- `git worktree add <workspace> -b <candidate_branch> origin/<default_branch>`.

It still does not create commits, open pull requests, merge branches, accept
candidate specs, write Ontology packages, or publish read models. The generated
worktree receives a local `.platform/graph_repository_worktree_prepare_report.json`
report with the executed commands and authority boundary.

## Commit Worktree

Create a review commit from explicitly materialized candidate paths:

```bash
scripts/platform.py graph-repository commit-worktree \
  --prepare-report .platform/candidates/my-idea-v1-worktree/.platform/graph_repository_worktree_prepare_report.json \
  --worktree-dir .platform/candidates/my-idea-v1-worktree \
  --path specs/nodes/SG-SPEC-CANDIDATE.yaml \
  --message "Add candidate spec graph"
```

`commit-worktree` stages only paths passed through `--path`. Paths must be
relative to the worktree and must not escape it. The command verifies that the
worktree is on the candidate branch recorded by `prepare-worktree`, then creates
a candidate-branch commit and writes
`.platform/graph_repository_review_commit_report.json`.

This still does not open a pull request, merge, accept candidate specs into the
canonical branch, write Ontology packages, or publish read models.

## Open Review

Push the candidate branch and open a pull request after a successful review
commit:

```bash
scripts/platform.py graph-repository open-review \
  --commit-report .platform/candidates/my-idea-v1-worktree/.platform/graph_repository_review_commit_report.json \
  --worktree-dir .platform/candidates/my-idea-v1-worktree \
  --base main \
  --title "Add candidate spec graph" \
  --body "Review candidate spec graph produced from the idea-to-spec flow."
```

`open-review` verifies that the worktree is still on the candidate branch and
that `HEAD` matches the commit recorded by `commit-worktree`. It then executes:

- `git push -u origin <candidate_branch>`;
- `gh pr create ...`.

The command writes `.platform/graph_repository_open_review_report.json` with
the review URL. It still does not merge, accept candidate specs into the
canonical branch, write Ontology packages, or publish read models.

## Review Status

Read pull request state after `open-review`:

```bash
scripts/platform.py graph-repository review-status \
  --open-review-report .platform/candidates/my-idea-v1-worktree/.platform/graph_repository_open_review_report.json \
  --worktree-dir .platform/candidates/my-idea-v1-worktree
```

`review-status` runs `gh pr view` and writes
`.platform/graph_repository_review_status_report.json`. It normalizes the review
state as `open`, `draft`, `closed`, `merged`, or `unknown`.

This command is read-only with respect to the graph lifecycle. It does not merge,
accept candidate specs into the canonical branch, write Ontology packages, or
publish read models. A later publish slice can consume a `merged` status report.

## Publish Read Model

Publish a public-safe read-model bundle after the review is merged:

```bash
scripts/platform.py graph-repository publish-read-model \
  --review-status-report .platform/candidates/my-idea-v1-worktree/.platform/graph_repository_review_status_report.json \
  --bundle-dir ../SpecGraph/dist/specgraph-public \
  --output-dir dist/specgraph-public
```

`publish-read-model` requires a `merged` review status report and a bundle
manifest, defaulting to `artifact_manifest.json`. It copies the bundle into a
new output directory and writes
`.platform/graph_repository_publish_read_model_report.json`.

The command does not mutate canonical specs, write Ontology packages, merge
branches, or publish private artifacts. It assumes the source bundle has already
passed the SpecGraph public-safe publish gates.
