# Product Idea-to-Spec Demo Runbook

This runbook describes a local end-to-end demo of the product
`idea_to_spec` lifecycle across SpecGraph, SpecSpace, Metrics, and Platform.
It is intentionally operator-driven and does not grant UI write authority.

## Goal

Show how a product idea becomes a reviewable SpecGraph candidate, how
SpecSpace displays the candidate lifecycle and Idea Maturity diagnostics, and
how Platform gates repair, approval, and Git Service promotion handoffs.

The demo has two useful outcomes:

- a diagnostic demo, where the candidate is blocked and the UI/report explains
  why;
- a happy-path promotion demo, only when repair answers, ontology decisions,
  approval intent, and approval-ready repaired handoff artifacts are present
  for the same workspace/session.

## Preflight

Use clean, current checkouts:

```bash
git -C ../Metrics status -sb
git -C ../SpecGraph status -sb
git -C ../SpecSpace status -sb
git -C . status -sb
```

All four repositories should be on their intended branches. Generated
`runs/*.json` and `dist/specgraph-public/*` files are normally ignored, but
they still affect local demos.

Before running Platform smoke, ensure SpecSpace-owned state artifacts in
`../SpecGraph/runs` belong to the workspace being demonstrated:

```bash
python3 - <<'PY'
import json
from pathlib import Path

runs = Path("../SpecGraph/runs")
for name in [
    "idea_to_spec_repair_rerun_requests.json",
    "idea_to_spec_candidate_approval_intents.json",
    "specspace_repair_draft_import_preview.json",
    "specspace_repair_rerun_request_gate.json",
]:
    path = runs / name
    if not path.exists():
        print(name, "missing")
        continue
    data = json.loads(path.read_text())
    print(name, data.get("summary"))
PY
```

If these artifacts point at another workspace, the gate should block with an
identity mismatch. That is correct behavior, not a Platform failure.

## 1. Build SpecGraph Product Artifacts

From `../SpecGraph`:

```bash
make product-workspace-decision-backed-repair-chain
make product-workspace-repaired-promotion-handoff
make publish-bundle
python3 tools/build_static_artifact_bundle.py \
  --output-dir dist/specgraph-public/workspaces/team-decision-log
```

Checkpoints:

- `runs/idea_maturity_metrics_report.json` exists;
- `runs/idea_maturity_metrics_validation_report.json` exists and is `ok`;
- `runs/repaired_candidate_promotion_handoff_report.json` exists;
- `dist/specgraph-public/artifact_manifest.json` contains the maturity reports;
- `dist/specgraph-public/workspaces/team-decision-log/artifact_manifest.json`
  contains the product workspace maturity, repaired handoff, project-local
  ontology effect, and candidate overview artifacts.

Quick check:

```bash
python3 - <<'PY'
import json
from pathlib import Path

root = Path("../SpecGraph")
report = json.loads((root / "runs/idea_maturity_metrics_report.json").read_text())
validation = json.loads((root / "runs/idea_maturity_metrics_validation_report.json").read_text())
handoff = json.loads((root / "runs/repaired_candidate_promotion_handoff_report.json").read_text())

print("maturity:", report.get("status"), report.get("summary", {}).get("lifecycle_state"))
print("validation:", validation.get("summary", {}).get("status"))
print("handoff:", handoff.get("summary", {}).get("status"))
print("approval-ready:", handoff.get("summary", {}).get("ready_for_candidate_approval"))
print("unresolved ontology gaps:", handoff.get("summary", {}).get("unresolved_ontology_gap_count"))
print("unresolved candidate gaps:", handoff.get("summary", {}).get("unresolved_candidate_gap_count"))
PY
```

## 2. Start SpecSpace Against The Public Bundle

In one terminal, serve the static SpecGraph bundle:

```bash
python3 -m http.server 9009 \
  --bind 127.0.0.1 \
  --directory ../SpecGraph/dist/specgraph-public
```

In another terminal, start the SpecSpace API with the product workspace mapped
to the same bundle:

```bash
SPECGRAPH_DIR="${SPECGRAPH_DIR:-../SpecGraph}"
DIALOG_DIR="${DIALOG_DIR:-../ChatGPTDialogs/canonical_json}"

uv run --with-requirements requirements.txt --with-requirements requirements-dev.txt \
  python viewer/server.py \
    --host 127.0.0.1 \
    --port 8001 \
    --dialog-dir "$DIALOG_DIR" \
    --spec-dir "$SPECGRAPH_DIR/specs/nodes" \
    --specgraph-dir "$SPECGRAPH_DIR" \
    --artifact-base-url http://127.0.0.1:9009 \
    --product-workspace-artifact-base-url team-decision-log=http://127.0.0.1:9009/workspaces/team-decision-log \
    --agent
```

Set `DIALOG_DIR` explicitly if your canonical dialog export is not available
at the sibling `../ChatGPTDialogs/canonical_json` path.

In a third terminal, start the new SpecSpace UI. Do not start the deprecated
ContextBuilder UI for this demo.

```bash
npm run dev --prefix graphspace -- --host 127.0.0.1 --port 5175
```

Open:

```text
http://127.0.0.1:5175/team-decision-log
```

API checkpoint:

```bash
python3 - <<'PY'
import json
import urllib.request

url = "http://127.0.0.1:8001/api/v1/idea-to-spec-workspace?workspace=team-decision-log"
data = json.load(urllib.request.urlopen(url))
idea_maturity = data.get("idea_maturity", {})
state_hygiene = data.get("workspace_state_hygiene", {})

print("workspace:", data.get("workspace", {}).get("id"))
print("idea maturity:", idea_maturity.get("status"), "trusted=", idea_maturity.get("trusted"))
print("validation:", (idea_maturity.get("validation") or {}).get("summary", {}).get("status"))
print("repair approval ready:", (data.get("repair_session") or {}).get("summary", {}).get("ready_for_candidate_approval"))
print("workspace state:", (state_hygiene.get("summary") or {}).get("status"))
PY
```

Optional Platform preflight evidence:

```bash
curl -fsS \
  "http://127.0.0.1:8001/api/v1/idea-to-spec-workspace-state-hygiene?workspace=team-decision-log" \
  > ../SpecGraph/runs/workspace_state_hygiene_report.json
```

This captures SpecSpace-owned state hygiene as report-only telemetry for the
Platform smoke. It helps identify stale local repair drafts, rerun requests, or
approval intents before they become opaque handoff failures.

Expected UI checkpoints:

- Product Workspace route renders from GraphSpace, not legacy ContextBuilder;
- Idea Maturity panel is available and trusted;
- Workspace state preflight is visible and has no stale or invalid blockers for
  a clean happy path;
- repair/session/promotion sections explain current blockers;
- if repaired handoff is not approval-ready, the UI should not offer a fake
  Git promotion path.

## 3. Run Platform Repair Smoke

From `Platform`:

```bash
scripts/platform.py product-repair-rerun smoke \
  --specgraph-dir ../SpecGraph \
  --build-repaired-handoff \
  --profile diagnostic-blocked \
  --workspace-state-hygiene ../SpecGraph/runs/workspace_state_hygiene_report.json \
  --format json
```

Expected diagnostic result when the workspace/session state is incomplete:

- `ok: true`;
- `summary.profile: diagnostic-blocked`;
- `summary.strict_status: failed`;
- no Git commands executed;
- no candidate approval decision materialized;
- no branch, commit, pull request, ontology write, or canonical spec mutation;
- diagnostics identify the first broken handoff, usually stale SpecSpace-owned
  rerun request state or unresolved repaired handoff gaps;
- `workspace_state_hygiene.recommended_actions` names the next safe operator
  step, such as rebuilding the repair draft import preview or recreating the
  rerun request for the current repair session.

For a happy-path Team Decision Log demo after SpecGraph has produced the
workspace/session-consistent repair pack:

```bash
scripts/platform.py product-repair-rerun smoke \
  --specgraph-dir ../SpecGraph \
  --build-repaired-handoff \
  --profile happy-path-promotion-dry-run \
  --workspace-state-hygiene ../SpecGraph/runs/workspace_state_hygiene_report.json \
  --format json
```

Expected happy-path result when the repair request and repaired handoff are
ready for the same workspace/session:

- `ok: true`;
- `summary.profile: happy-path-promotion-dry-run`;
- `summary.strict_status: passed`;
- `plan_ok: true`;
- `execution_ok: true`;
- `publication_ok: true`;
- `candidate_approval_gate_ok: true`;
- `ready_to_materialize: true`.

## 4. Validate Candidate Approval Boundary

Diagnostic mode:

```bash
scripts/platform.py product-candidate-approval approve \
  --specgraph-dir ../SpecGraph \
  --workspace-id team-decision-log \
  --repair-session runs/repaired_idea_to_spec_repair_session.json \
  --active-candidate runs/repaired_active_idea_to_spec_candidate.json \
  --promotion-gate runs/repaired_idea_to_spec_promotion_gate.json \
  --repaired-handoff runs/repaired_candidate_promotion_handoff_report.json \
  --dry-run \
  --format json
```

Expected blocked result:

- `status: candidate_approval_blocked`;
- `decision_written: false`;
- diagnostics mention missing approval intent, unresolved gaps, or repaired
  handoff not ready.

Happy path, after SpecSpace records approval intent and the repaired handoff is
approval-ready:

```bash
scripts/platform.py product-candidate-approval approve \
  --specgraph-dir ../SpecGraph \
  --workspace-id team-decision-log \
  --repair-session runs/repaired_idea_to_spec_repair_session.json \
  --active-candidate runs/repaired_active_idea_to_spec_candidate.json \
  --promotion-gate runs/repaired_idea_to_spec_promotion_gate.json \
  --repaired-handoff runs/repaired_candidate_promotion_handoff_report.json \
  --path runs/materialized_candidate_specs/CANDIDATE-CANDIDATE-SPEC-PRODUCT-BOUNDARY.yaml \
  --output ../SpecGraph/runs/platform_candidate_approval_execution_report.json \
  --decision-output ../SpecGraph/runs/candidate_approval_decision.json
```

Use the actual promotion paths from the repaired promotion gate, not the example
path above.

## 5. Promotion Request And Git Service Dry Run

Only run these commands after `candidate_approval_decision.json` is fresh and
approved.

Build the graph repository plan:

```bash
scripts/platform.py graph-repository plan \
  --contract graph-repository-service.example.json \
  --runs-dir ../SpecGraph/runs \
  --repaired-handoff ../SpecGraph/runs/repaired_candidate_promotion_handoff_report.json \
  --output ../SpecGraph/runs/graph_repository_execution_plan.json
```

Create the report-only promotion request:

```bash
scripts/platform.py product-candidate-promotion request \
  --plan ../SpecGraph/runs/graph_repository_execution_plan.json \
  --approval-decision ../SpecGraph/runs/candidate_approval_decision.json \
  --output ../SpecGraph/runs/graph_repository_promotion_request.json
```

Run a dry-run promotion execution:

```bash
scripts/platform.py product-candidate-promotion execute \
  --promotion-request ../SpecGraph/runs/graph_repository_promotion_request.json \
  --approval-decision ../SpecGraph/runs/candidate_approval_decision.json \
  --repository-dir ../SpecGraph \
  --workspace-dir /tmp/specgraph-product-promotion-demo-worktree \
  --dry-run \
  --open-review-dry-run \
  --output ../SpecGraph/runs/product_candidate_promotion_execution_report.json
```

Expected dry-run result:

- no branch, commit, or pull request is created;
- the candidate workspace/worktree directory is not created by the dry-run;
- the execution report explains the planned Git Service operations;
- SpecSpace can display the resulting product promotion execution surface.

## Team Decision Log Demo Status

The historical Team Decision Log diagnostic run produced a valid public bundle
and trusted Idea Maturity metrics, but did not reach candidate approval:

```text
idea_maturity.status: blocked
idea_maturity.validation: ok
repaired_handoff.status: repaired_candidate_promotion_handoff_review_required
repaired_handoff.ready_for_candidate_approval: false
unresolved ontology gaps: 10
unresolved candidate gaps: 3
```

Platform correctly refused to continue:

```text
product-repair-rerun smoke: failed before execution because local rerun request
state belonged to local-subscription-control while the current repair session
belonged to team-decision-log.

product-candidate-approval approve --dry-run: candidate_approval_blocked
because approval intent was missing and the repaired handoff still had
unresolved gaps.

graph-repository plan --repaired-handoff: blocked all Git Service operations
because the repaired handoff was not approval-ready.
```

This remains a successful diagnostic demo when run with
`--profile diagnostic-blocked`.

For the happy-path demo, SpecGraph provides a workspace/session-consistent Team
Decision Log repair pack. Run the SpecGraph happy-path repair pack target first,
then run the Platform smoke with `--profile happy-path-promotion-dry-run`. The
latest local promotion dry-run pass reached the intended boundary:

```text
product-repair-rerun smoke:
  profile_status: passed
  profile_observed: happy_path_ready
  ready_to_materialize: true
  candidate_approval_approved_path_count: 6
  published_artifact_count: 12

product-candidate-approval approve:
  status: candidate_approval_materialized
  decision_written: true
  approved_path_count: 6

product-candidate-promotion request:
  promotion_ready: true
  commit_path_count: 6

product-candidate-promotion execute --dry-run --open-review-dry-run:
  status: dry_run
  review_opened: false
  commit_created: false
  read_model_published: false
```

This reaches candidate approval, promotion request, and Git Service dry-run
visibility without creating a branch, commit, pull request, ontology write, or
canonical spec mutation.

## Production Team Decision Log Smoke Status

After the Timeweb product artifact base fix and the SpecGraph workspace bundle
publish slice, the production Team Decision Log route now resolves product
workspace artifacts from the workspace-specific static base:

```text
https://specgraph.space/team-decision-log
https://specgraph.tech/workspaces/team-decision-log/artifact_manifest.json
```

Expected production routing checks:

```text
GET https://specgraph.tech/workspaces/team-decision-log/artifact_manifest.json -> 200
GET https://specgraph.tech/workspaces/team-decision-log/runs/idea_maturity_metrics_report.json -> 200
GET https://specgraph.tech/workspaces/team-decision-log/runs/repaired_candidate_promotion_handoff_report.json -> 200
```

The latest production smoke confirmed that `/team-decision-log` no longer reads
the root SpecGraph showcase bundle. The SpecSpace workspace API reported an
`http-product-workspace` provider with:

```text
artifact_base_url: https://specgraph.tech/workspaces/team-decision-log
selected_workspace_id: team-decision-log
missing_artifact_count: 0
idea_maturity: available, trusted=true
repaired_handoff.ready_for_candidate_approval: true
resolved_ontology_gap_count: 11
unresolved_ontology_gap_count: 0
promotion_path_count: 6
```

The remaining production blocker is not static artifact routing. It is
SpecSpace-owned mutable state hygiene: production can still hold stale
draft/request/gate state from an older repair session while the published
read-only happy-path bundle is already approval-ready. In that case the guided
flow should stay blocked and explain the next safe action, for example:

```text
workspace_state_hygiene.status: blocked
repair_drafts: missing
repair_rerun_request: missing
candidate_approval_intent: missing
repair_draft_import_preview: stale repair_session_ref_mismatch
repair_rerun_request_gate: stale repair_session_ref_mismatch
next_action: Rebuild repair_draft_import_preview for the current repair session.
```

Treat this as a separate UX/policy task. SpecSpace should not silently mutate or
clear operator-owned state; it should make the stale state visible and require an
explicit safe operator action.

## Manual Repair Loop Smoke Status

The manual repair loop smoke exercises the operator path rather than the
pre-seeded happy-path fixture pack. In the latest end-to-end run, operator-owned
drafts created through SpecSpace were accepted as handoff state, imported by
SpecGraph, and carried through to the same controlled promotion dry-run boundary:

```text
SpecSpace UI repair drafts
  -> SpecSpace-owned draft and rerun request state
  -> SpecGraph import preview and request gate
  -> SpecGraph repair-draft rerun
  -> repaired handoff ready_for_candidate_approval=true
  -> Platform candidate approval materialization
  -> Platform promotion request
  -> Git Service dry-run
```

Confirmed smoke result:

```text
manual repair drafts: accepted by SpecSpace-owned state
SpecGraph rerun: produced repaired candidate handoff
repaired handoff: approval-ready
workspace hygiene: consumed source state treated as usable, not stale
candidate approval decision: materialized
promotion request: promotion_ready=true
Git Service dry-run: ok=true
worktree_created: false
commit_created: false
pull_request_opened: false
read_model_published: false
```

This confirms the downstream product flow is usable without relying only on the
fixture repair pack. The important lifecycle rule is that source drafts, rerun
requests, import previews, and request gates may legitimately refer to the
original repair session after a repaired handoff is selected. When the repaired
handoff records them as provenance, they are consumed source state rather than
stale state. The next safe operator action after an approval-ready repaired
handoff is candidate approval intent, not a forced rebuild of the already
consumed source handoff.

Authority boundaries remain unchanged:

- SpecSpace stores operator intent but does not execute SpecGraph, Platform, or
  Git Service.
- SpecGraph builds review-only rerun and repaired handoff artifacts but does not
  mutate canonical specs, write Ontology packages, or accept ontology terms.
- Platform materializes candidate approval and promotion handoff artifacts only
  after gates pass.
- Git Service dry-run does not create a worktree, commit, pull request, or read
  model publication.

## Real Idea Answer Continuation Handoff

After SpecSpace stores real-idea clarification answers, Platform can run the
controlled continuation handoff without giving SpecSpace execution authority:

```bash
scripts/platform.py product-real-idea-continuation execute \
  --specgraph-dir ../SpecGraph \
  --run-dir runs/<idea-smoke-run> \
  --format json
```

The command runs the fixed SpecGraph target:

```text
real-idea-intake-continue-from-specspace-answers
```

It writes:

```text
runs/platform_real_idea_answer_continuation_execution_report.json
```

and verifies that the run directory contains the expected import preview,
continuation report, validated answers, clarified intake session, candidate
source bridge report, and active candidate artifact.

This is still pre-promotion orchestration:

- no Git branch, commit, pull request, or read-model publication;
- no canonical spec mutation;
- no Ontology package write or term acceptance;
- no browser-side execution authority.

## Candidate Overview Narrative Smoke Status

The product workspace now has a read-only candidate overview surface that sits
above the lower-level repair, maturity, topology, and ontology review panels.
SpecGraph builds it with:

```bash
make candidate-overview
```

and the static artifact bundle includes:

```text
runs/candidate_overview.json
```

Expected workspace checks:

```text
candidate_overview.artifact_kind: candidate_overview
candidate_overview.summary.graph_source: one of repaired_candidate_graph, candidate_graph
candidate_overview.topology.relation_counts: includes workflow relation counts
candidate_overview.next_action.evidence_refs: public artifact refs only
```

In SpecSpace, `/team-decision-log` exposes the same data in the Product
Workspace **Candidate overview** section. The section explains:

- product intent and understood scope;
- actors, commands, domain events, policies, constraints, and candidate nodes;
- workflow topology relation counts and sample edges;
- project-local ontology review status;
- Idea Maturity / repair readiness;
- the next safe operator action with evidence refs.

This panel is navigation and explanation only. It does not execute SpecGraph,
apply answers, mutate specs, write Ontology packages, accept ontology terms,
approve candidates, create Git branches/commits/PRs, or publish read models.

## Project-Local Ontology Review Completion Status

The Team Decision Log happy-path repair pack now completes the project-local
ontology review loop as part of the demo surface. SpecGraph materializes
SpecSpace-owned keep-local decisions for the remaining required project-local
terms, validates them through the import preview, converts them into maturity
evidence, and refreshes the candidate overview.

Expected checks after:

```bash
make product-workspace-team-decision-log-happy-path-repair-pack
```

```text
runs/project_local_ontology_review_decisions.json:
  artifact_kind: specspace_project_local_ontology_review_decision_state
  summary.decision_count: 10
  summary.review_action: keep_project_local

runs/specspace_project_local_ontology_decision_import_preview.json:
  readiness.ready: true
  summary.accepted_decision_count: 10
  summary.missing_decision_count: 0
  summary.invalid_decision_count: 0

runs/project_local_ontology_decision_effect_report.json:
  readiness.ready: true
  summary.ready_for_maturity: true
  summary.blocking_decision_count: 0

runs/idea_maturity_metrics_report.json:
  summary.project_local_ontology_review_status: project_local_ontology_decision_effect_ready
  summary.project_local_ontology_accepted_decision_count: 10
  summary.remaining_blocker_count: 0

runs/candidate_overview.json:
  summary.project_local_ontology_review_status: project_local_ontology_decision_effect_ready
  sections.project_local_ontology.accepted_decision_count: 10
  sections.project_local_ontology.blocking_decision_count: 0
```

This remains review-only. Keeping a term project-local does not write an
Ontology package, update an ontology lockfile, accept a term globally, mutate
canonical specs, approve a candidate, or create Git state.

## Downstream Promotion After Overview Smoke Status

After the candidate overview and project-local ontology review completion
slices, the Team Decision Log demo still reaches the downstream promotion
dry-run boundary.

Confirmed local smoke sequence:

```text
SpecGraph happy-path repair pack
  -> candidate overview
  -> root and workspace static bundles
  -> SpecSpace Product Workspace API
  -> Platform happy-path repair smoke
  -> candidate approval materialization
  -> graph repository promotion request
  -> Git Service dry-run
```

Observed checkpoints:

```text
workspace artifact base: http://127.0.0.1:9009/workspaces/team-decision-log
workspace manifest: present
candidate_overview: available
candidate_overview.summary.ready_for_candidate_approval: true
candidate_overview.summary.project_local_ontology_review_status:
  project_local_ontology_decision_effect_ready
Idea Maturity: available, trusted=true
Idea Maturity project_local_ontology_review.ready_for_maturity: true
workspace_state_hygiene.status: ready
Platform product-repair-rerun smoke profile: happy-path-promotion-dry-run
Platform product-repair-rerun smoke profile_status: passed
candidate approval decision: materialized
promotion request: promotion_ready=true
Git Service dry-run: ok=true
physical worktree created: false
commit created: false
pull request opened: false
read model published: false
```

This confirms that Candidate Overview and project-local ontology review
accounting do not block the approval/promotion dry-run boundary.

Known follow-up issues from this smoke:

- **SpecSpace project-local ontology projection split.** Candidate Overview and
  Idea Maturity correctly use the project-local decision effect report, but the
  separate `project_local_ontology_review` workspace section still reflects the
  raw review lane and can show the same terms as unreviewed. SpecSpace should
  either show raw lane and effective review as distinct states or prefer the
  effect report when presenting completion status.
- **Stale readiness explainer after approval.** After
  `candidate_approval_decision.json` is materialized and promotion dry-run has
  executed, `idea_maturity_metrics_report.json` correctly reports
  `candidate_approval_decision_state: materialized` and
  `platform_promotion_state: dry_run`, but still includes the old
  `candidate_approval_decision_missing` readiness explainer. Candidate Overview
  inherits that stale next action. SpecGraph should suppress resolved
  explainers or attach an explicit `resolved` state.
- **SpecSpace approval readiness projection.** The workspace API can still show
  `candidate_approval_decision_ready: false` after the approval decision exists,
  while the controlled promotion section reads the product promotion execution
  artifacts. SpecSpace should reconcile approval readiness with the materialized
  approval execution/decision artifacts.
- **Git dry-run summary wording.** Platform reports
  `summary.worktree_prepared: true` for a dry-run prepare-worktree stage even
  though the physical worktree path does not exist. The report should distinguish
  logical dry-run preparation from a real worktree creation, for example with
  `physical_worktree_created: false`.
