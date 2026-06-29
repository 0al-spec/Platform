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

For a step-by-step local product demo that exercises SpecGraph artifact
generation, SpecSpace Product Workspace visibility, Idea Maturity diagnostics,
Platform repair smoke, candidate approval, and Git Service dry-run boundaries,
see [Product Idea-to-Spec Demo Runbook](product-idea-to-spec-demo-runbook.md).

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

## Product Repair Rerun Execution

Before Git Service promotion, a product workspace may need one more controlled
repair rerun from SpecSpace-owned draft answers. The `product-repair-rerun`
adapter is the Platform-owned execution boundary for that step.

It consumes:

- `runs/idea_to_spec_repair_rerun_requests.json`;
- `runs/specspace_repair_draft_import_preview.json`;
- `runs/specspace_repair_rerun_request_gate.json`;
- `runs/idea_to_spec_repair_session.json`;
- `deployment-profile.product-idea-to-spec.example.json`.

The plan step validates the handoff and writes a durable execution plan:

```bash
scripts/platform.py product-repair-rerun plan \
  --specgraph-dir ../SpecGraph \
  --output ../SpecGraph/runs/platform_product_repair_rerun_execution_plan.json
```

The execute step runs only the make target selected by the SpecGraph request
gate:

```bash
scripts/platform.py product-repair-rerun execute \
  --plan ../SpecGraph/runs/platform_product_repair_rerun_execution_plan.json \
  --output ../SpecGraph/runs/platform_product_repair_rerun_execution_report.json
```

When the operator wants the repaired candidate to become approval-reviewable in
the same controlled run, execute can also run the fixed SpecGraph repaired
handoff target:

```bash
scripts/platform.py product-repair-rerun execute \
  --plan ../SpecGraph/runs/platform_product_repair_rerun_execution_plan.json \
  --build-repaired-handoff \
  --output ../SpecGraph/runs/platform_product_repair_rerun_execution_report.json
```

That mode verifies these additional SpecGraph outputs:

- `runs/repaired_candidate_promotion_handoff_report.json`;
- `runs/repaired_active_idea_to_spec_candidate.json`;
- `runs/repaired_idea_to_spec_repair_session.json`;
- `runs/repaired_idea_to_spec_promotion_gate.json`.

The publish step refreshes and verifies the public-safe SpecGraph bundle:

```bash
scripts/platform.py product-repair-rerun publish \
  --execution-report ../SpecGraph/runs/platform_product_repair_rerun_execution_report.json \
  --output ../SpecGraph/runs/platform_product_repair_rerun_publication_report.json
```

For demos and CI smoke checks, Platform can run the whole repair rerun boundary
as one end-to-end contract:

```bash
scripts/platform.py product-repair-rerun smoke \
  --specgraph-dir ../SpecGraph \
  --output ../SpecGraph/runs/platform_product_repair_rerun_smoke_report.json
```

The smoke command performs `plan -> execute -> publish`, writes the intermediate
reports, and then emits `platform_product_repair_rerun_smoke_report`. It proves
that the selected SpecSpace draft request can be validated, executed through the
single approved SpecGraph make target, published as public-safe artifacts, and
observed without starting candidate approval or Git Service promotion.

When SpecGraph has produced `runs/idea_maturity_metrics_report.json` and
`runs/idea_maturity_metrics_validation_report.json`, the publish and smoke
reports also include a compact `idea_maturity` summary. Platform exposes the
metrics status, validation status, lifecycle state, blockers, stale refs, failed
gates, dry-run count, bounded readiness explainers, source refs, and public
bundle presence. When the Metrics contract metadata is present, the same summary
also surfaces the report schema, validation report schema, validator id/version,
and compatibility policy refs used to interpret the telemetry. Readiness
explainers are operator-facing reasons with source evidence and `next_action`
text, for example unresolved Pre-SIB findings or repair-session blockers. This
is report-only telemetry: missing or failed maturity metrics make the maturity
surface untrusted, but they do not replace the concrete repair, approval, and
promotion gates.

The smoke can also include the repaired handoff and candidate approval gate:

```bash
scripts/platform.py product-repair-rerun smoke \
  --specgraph-dir ../SpecGraph \
  --build-repaired-handoff \
  --output ../SpecGraph/runs/platform_product_repair_rerun_smoke_report.json
```

With `--build-repaired-handoff`, the smoke performs
`plan -> execute -> publish -> product-candidate-approval gate`. This validates
that the repaired candidate artifacts are public-safe and ready for later
`candidate_approval_decision.json` materialization. It still does not
materialize that decision, create a branch, open a pull request, publish a read
model, accept ontology terms, write Ontology packages, or mutate canonical
specs.

This adapter may execute the controlled SpecGraph rerun make target and
`make publish-bundle`. It still must not create Git branches, commits, pull
requests, accept ontology terms, write Ontology packages, mutate canonical
specs, or promote a candidate. Those remain separate Git Service and
candidate-approval boundaries.

## Product Candidate Approval Intent Gate

After a repair session is ready and public-safe rerun artifacts are published,
SpecSpace may record an operator intent that the candidate is ready for
promotion review. This intent is still not a final Git Service approval and
does not create branches, commits, or pull requests.

Platform validates that handoff with `product-candidate-approval gate`. It
consumes:

- `runs/idea_to_spec_candidate_approval_intents.json`;
- `runs/idea_to_spec_repair_session.json`;
- `runs/idea_to_spec_promotion_gate.json`;
- `runs/platform_product_repair_rerun_execution_report.json`;
- `runs/platform_product_repair_rerun_publication_report.json`;
- explicit promotion paths supplied by the operator.

The product-level approval handoff can run the gate and materialize the narrow
approval decision in one audited step:

```bash
scripts/platform.py product-candidate-approval approve \
  --specgraph-dir ../SpecGraph \
  --workspace-id team-decision-log \
  --path specs/nodes/SG-SPEC-CANDIDATE.yaml \
  --output ../SpecGraph/runs/platform_candidate_approval_execution_report.json \
  --decision-output ../SpecGraph/runs/candidate_approval_decision.json
```

The approval execution report records the gate report ref, materialized
decision ref, approved paths, selected SpecSpace intent, and authority boundary.
It still does not run Git Service promotion, create branches or commits, open
pull requests, publish read models, mutate canonical specs, write Ontology
packages, or accept ontology terms.

The lower-level gate remains available when an operator needs to inspect the
readiness decision before materialization:

```bash
scripts/platform.py product-candidate-approval gate \
  --specgraph-dir ../SpecGraph \
  --workspace-id team-decision-log \
  --path specs/nodes/SG-SPEC-CANDIDATE.yaml \
  --output ../SpecGraph/runs/platform_candidate_approval_intent_gate_report.json
```

When SpecGraph has produced the repaired promotion handoff from proposal `0177`,
the gate can validate that repaired chain directly instead of comparing the
SpecSpace intent against the default active-candidate and promotion-gate refs.
Relative artifact paths in this invocation are resolved under `--specgraph-dir`,
so the command can be run from the Platform checkout:

```bash
scripts/platform.py product-candidate-approval gate \
  --specgraph-dir ../SpecGraph \
  --workspace-id local-subscription-control \
  --active-candidate runs/repaired_active_idea_to_spec_candidate.json \
  --repair-session runs/repaired_idea_to_spec_repair_session.json \
  --promotion-gate runs/repaired_idea_to_spec_promotion_gate.json \
  --repaired-handoff runs/repaired_candidate_promotion_handoff_report.json \
  --path specs/nodes/SUBSCRIPTION-CANDIDATE.yaml \
  --output ../SpecGraph/runs/platform_candidate_approval_intent_gate_report.json
```

In this mode the gate checks that the repaired handoff is ready, still
candidate-approval-only, has no unresolved repaired ontology/product gaps, and
points at the same active candidate, repair session, and promotion gate artifacts
selected by the invocation.

The gate report is read-only. It checks that the SpecSpace state is owned by
SpecSpace, the active intent is still `requested`, repair-session readiness is
`ready_for_candidate_approval`, repair rerun execution/publication are
successful non-dry-run reports, no ontology/spec/Git authority has expanded,
and the approved paths are safe relative repository paths.

The gate report also carries the same compact `idea_maturity` summary when the
SpecGraph maturity artifacts are present. The summary helps an operator inspect
pre-SIB/product maturity and its readiness explainers, but the gate continues to
base readiness on concrete handoff artifacts and explicit approved paths.
Platform does not apply a score threshold from the metrics report.

When the gate is ready, Platform can materialize the narrow handoff artifact
that the Git Service already expects:

```bash
scripts/platform.py product-candidate-approval materialize \
  --gate-report ../SpecGraph/runs/platform_candidate_approval_intent_gate_report.json \
  --output ../SpecGraph/runs/candidate_approval_decision.json
```

`candidate_approval_decision.json` is an approval decision for promotion
review, not a Git operation. It still does not mutate canonical specs, write
Ontology packages, accept ontology terms, create a branch, open a pull request,
or publish a read model. Those actions remain under the later
`graph-repository promotion-request` and `git-service execute-promotion`
contracts.

## Product Promotion Request Handoff

After `candidate_approval_decision.json` exists, Platform can build the
Graph Repository promotion request without requiring the operator to retype the
candidate id or approved materialized paths:

```bash
scripts/platform.py product-candidate-promotion request \
  --plan ../SpecGraph/runs/graph_repository_execution_plan.json \
  --approval-decision ../SpecGraph/runs/candidate_approval_decision.json \
  --output ../SpecGraph/runs/graph_repository_promotion_request.json
```

This command is a product-aware wrapper around the generic
`graph-repository promotion-request` contract. It derives:

- `candidate_id` from `candidate_approval_decision.candidate.candidate_id`;
- `workflow_lane` from `candidate_approval_decision.workspace.mode`;
- `target_repository_role` from
  `candidate_approval_decision.workspace.repository_role`;
- `commit_paths` from `candidate_approval_decision.promotion_request.paths`;
- review title/body from CLI overrides or approval-decision metadata.

The wrapper rejects the handoff when:

- the Graph Repository plan is not `ok` or not `ready_for_branch`;
- the approval decision is not `approved` and ready;
- approval-decision authority flags are missing or not literally `false`;
- the workflow lane or repository role is not product-scoped;
- approved paths are unsafe or outside the supported promotion roots;
- the derived request would not match the approval decision expected by the
  Git Service validator.

The output remains report-only:

- no Git branch or worktree is created;
- no commit is created;
- no pull request is opened;
- no read model is published;
- no SpecGraph or Ontology canonical state is mutated.

## Product Controlled Promotion Execution

After a product promotion request is ready, Platform can execute the controlled
Git Service promotion flow from the product-scoped handoff:

```bash
scripts/platform.py product-candidate-promotion execute \
  --promotion-request ../SpecGraph/runs/graph_repository_promotion_request.json \
  --approval-decision ../SpecGraph/runs/candidate_approval_decision.json \
  --repository-dir ../SpecGraph \
  --workspace-dir .platform/candidates/team-decision-log-worktree \
  --materialized-source-dir ../SpecGraph/runs/materialized_candidate_specs \
  --open-review-dry-run \
  --output ../SpecGraph/runs/product_candidate_promotion_execution_report.json
```

This command is a product-aware wrapper around
`git-service execute-promotion`. It revalidates the promotion request,
candidate approval decision, deployment profile, and Git Service operation
contract before invoking the lower-level executor. In non-dry-run mode it may
prepare a candidate worktree/branch and create a candidate commit. When
`--open-review-dry-run` is omitted, it may also push the candidate branch and
open a review pull request through `gh`.

The product execution report is:

```text
runs/product_candidate_promotion_execution_report.json
```

It records:

- the promotion request and approval decision refs;
- the inner Git Service execution report ref;
- normalized child report refs for prepare, commit, and open-review steps;
- a `git_review` summary with candidate branch, worktree, commit SHA, PR URL
  and PR number when those reports exist;
- the candidate branch;
- copied materialized paths;
- prepare/commit/open-review operation statuses;
- whether the run was a dry-run or open-review dry-run;
- authority boundary facts for worktree/branch creation, candidate commit, and
  pull request opening.

The command still does not auto-merge pull requests, publish read models, accept
candidate specs into canonical state, write Ontology packages, or accept
Ontology terms. Post-review read-model publication remains a separate
`review-status` / `publish-read-model` step after the pull request is merged.

## Product Post-Review Read-Model Publication

After the review pull request exists, product promotion continues through two
product-aware wrappers. The first one inspects review state from the product
execution report:

```bash
scripts/platform.py product-candidate-promotion review-status \
  --execution-report ../SpecGraph/runs/product_candidate_promotion_execution_report.json \
  --output ../SpecGraph/runs/product_candidate_promotion_review_status_report.json
```

This wraps `graph-repository review-status` and writes:

```text
runs/product_candidate_promotion_review_status_report.json
```

The report is read-only. It requires a non-dry-run product execution, a real
open-review report, and a `product_idea_to_spec` workflow lane. It records the
generic review-status report ref and whether read-model publication is still
blocked or ready after a merged review.

When the review is merged, the public-safe read model can be published through:

```bash
scripts/platform.py product-candidate-promotion publish-read-model \
  --review-status-report ../SpecGraph/runs/product_candidate_promotion_review_status_report.json \
  --bundle-dir ../SpecGraph/dist/specgraph-public \
  --output-dir /srv/specspace/workspaces/team-decision-log \
  --output ../SpecGraph/runs/product_candidate_promotion_read_model_publication_report.json
```

This wraps `graph-repository publish-read-model` and writes:

```text
runs/product_candidate_promotion_read_model_publication_report.json
```

The command copies only the supplied public-safe bundle to the selected
read-model output directory. It does not merge the review, open pull requests,
mutate canonical specs without review, write Ontology packages, accept Ontology
terms, or publish private artifacts.

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
- `idea_to_spec_rerun_materialization.json`;
- `idea_to_spec_repair_session.json`.

The clarification request artifact is retained as review evidence even when its
own readiness state still says `clarification_required`; the accepted answers,
typed ontology decisions, rerun input, rerun preview, and rerun materialization
must be ready before branch preparation. The repair session journal is the
durable handoff state: it must remain review-only, reference the expected
source artifacts, identify the same product candidate/workspace, report ready
intermediate artifacts, and set `ready_for_candidate_approval: true` before the
Graph Repository Service can mark branch preparation ready. If the rerun
preview, materialized candidate preview, or repair session journal still reports
unresolved ontology gaps, the plan remains `ready_for_branch: false`.

`ready_for_platform_promotion` is intentionally not required at this stage. It
becomes relevant only after a separate `candidate_approval_decision` authorizes
promotion into the Git Service flow.

Each artifact must remain review-only:

- `canonical_mutations_allowed: false`;
- `tracked_artifacts_written: false`.

The repair session journal additionally must keep all authority flags false,
including branch/commit creation, prompt execution, candidate mutation, ontology
term acceptance, ontology package writes, pull request creation, and read-model
publication. Its privacy boundary must keep raw idea text, raw prompts, raw
model output, and raw operator notes unpublished.

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
