# Ontology-SpecGraph-SpecSpace Roadmap

## Purpose

This document records the cross-repository roadmap for the Ontology,
SpecGraph, and SpecSpace line. It is an operator coordination note, not a
canonical contract for any single repository.

Canonical contracts, schemas, runtime code, and tests still belong in the
repository that owns the behavior:

- Ontology owns ontology package shape, `ontologyc`, Hypercode IR imports,
  governance checks, and accepted ontology package drafts.
- SpecGraph owns graph-side import boundaries, derived review artifacts,
  supervisor gates, and proposal review.
- SpecSpace owns read-only viewer/API surfaces over SpecGraph-derived
  artifacts and SpecSpace-owned workbench state.
- Platform owns deploy/process coordination only after the upstream contracts
  are stable.

## Current Anchors

As of 2026-07-09:

- Ontology PR `#53` is merged: `ontologyc` adapter report artifact line.
- Ontology PR `#54` is merged: Hypercode IR v2 ontology package import.
- Ontology PR `#57` is merged: the curated `specgraph-core`
  `DomainOntologyPackage` exists as a compiler-backed package and remains usable
  as an example/fixture.
- Ontology PR `#59` is merged: `DomainOntologyPackage` supports optional
  ontology layer metadata, normalized IR carries layers, TypeScript outputs
  expose layers, and compatibility reports include layer changes.
- Ontology PR `#60` is merged: ONT-040 is selected and planned as the next
  compiler-side model applicability and structural change classification slice.
- SpecGraph proposal `0060` defines the external ontology import plane.
- SpecGraph `docs/ontologyc_adapter_report_contract.md` defines the
  `ontologyc validate-specgraph` adapter report boundary.
- SpecGraph proposal `0100` records the operator intent for
  ontology-grounded semantic control.
- SpecGraph proposals `0103` through `0115` are implemented:
  - `0103` semantic control policy;
  - `0104` semantic context pack;
  - `0105` semantic lint report;
  - `0106` ontology delta candidate review packet;
  - `0108` semantic review surface;
  - `0109` supervisor semantic gate evidence;
  - `0110` Ontology delta draft intake;
  - `0111` closed-loop evidence;
  - `0113` ontology review dashboard;
  - `0114` Ontology owner decision report contract;
  - `0115` decision import preview.
- SpecSpace has read-only consumers for:
  - ontology semantic review surface;
  - ontology review dashboard;
  - ontology owner decision review.
- SpecGraph and SpecSpace have since moved toward project-local ontology
  consumption: compiler artifacts are public-safe `runs` inputs, and SpecSpace
  shows a curated practical ontology/workbench surface rather than extracted
  topology/proposal text as ontology authority.
- SpecGraph proposals `0141` through `0143` are implemented:
  - `0141` consumes layer metadata from project-local ontology compiler artifacts;
  - `0142` reports layer-aware ontology gaps and compatibility diffs;
  - `0143` requires SpecAuthor generated artifacts to declare active ontology
    layer context before write-gate approval.
- SpecSpace PRs `#248` and `#249` are merged: the Ontology Workbench reads the
  consolidated ontology artifacts and exposes a read-only layer lens over package,
  gap, and diff layer data.
- SpecGraph PRs `#590`, `#591`, and `#592` are merged as a stacked SpecAuthor
  prompt-side sequence:
  - `#590` adds the deterministic SpecAuthor authoring flow that emits
    `runs/specauthor_invocation_artifact.json`;
  - `#591` publishes public-safe SpecAuthor invocation artifacts through the
    static bundle;
  - `#592` declares a local report-only SpecAuthorAgent Passport with
    experimental `x-behaviorPolicies`.
- SpecSpace PR `#251` is merged: the Ontology Workbench shows the SpecAuthor
  invocation chain as a read-only review lane.
- agent-passport PR `#6` is merged: `x-behaviorPolicies` is documented as an
  experimental `x-*` extension that remains report-only unless a consumer
  defines explicit enforcement semantics.
- SpecGraph proposals `0149` through `0155` are implemented for the first
  `product_idea_to_spec` line: event-storming intake, candidate graph contract,
  pre-SIB/coherence metrics, autonomous repair preview, materialized candidate
  previews, promotion gate, and active candidate source.
- SpecGraph publishes a product workspace candidate graph for the Team Decision
  Log pilot without treating it as SpecGraph bootstrap state.
- SpecSpace routes `specgraph.space/` and `specgraph.space/team-decision-log`
  as separate workspace views, and the product route reads product workspace
  artifacts instead of leaking bootstrap graph artifacts.
- Platform deployment profiles now separate `product_idea_to_spec` promotion
  from `specgraph_bootstrap` writes. Product promotion may target only
  `product_spec_workspace` repository roles, while bootstrap-internal Git
  Service writes remain dry-run-only.
- The Idea Maturity line is now end-to-end visible:
  - Metrics remains the source of truth for the idea maturity RFC, schema, and
    validator.
  - SpecGraph `0179` / PR `#632` publishes
    `runs/idea_maturity_metrics_report.json` and
    `runs/idea_maturity_metrics_validation_report.json` as part of dashboard-ready
    product/repaired flows.
  - SpecSpace PR `#284` shows a read-only Product Workspace Idea Maturity panel
    and keeps raw maturity JSON out of generic artifact previews.
  - Platform PR `#67` reads those artifacts as report-only telemetry in product
    publish/smoke/approval reports without replacing the real repair, approval,
    or promotion gates.
  - The next Platform slice surfaces Metrics contract metadata in those compact
    summaries, so operators can see the report schema, validation schema,
    validator id/version, and compatibility policy that made the telemetry
    trustworthy.
- The idea-to-spec product direction now has a working local managed lifecycle:
  SpecSpace can create a product workspace, collect raw idea and clarification
  state, call backend-managed Platform wrappers, show repair/approval/promotion
  progress, and display read-model publication after Git review. The next work
  is quality and production hardening: deterministic next-action ranking,
  fallback-free clarification templates, durable workspace bindings, and moving
  the local managed executor pattern toward hosted/queue-backed service
  execution.

The product intent is to reduce hallucinated terms, misunderstood domain
language, wrong aliases, wrong relation directions, and hidden missing concepts
in agent-generated specs, proposals, and review surfaces.

## Ownership Adjustment

The Ontology repository should not become a global storage location for product
ontologies created by arbitrary SpecGraph/SpecSpace workspaces. It owns:

- the `DomainOntologyPackage` schema and compiler;
- validation, normalization, diff, governance, and TypeScript emission behavior;
- reusable examples and fixtures such as `specgraph-core`.

Project/product ontology packages should live with the product graph or project
workspace that owns them, then be checked, compiled, diffed, and reviewed with
Ontology tooling. SpecGraph imports the resulting compiler artifacts and derived
review reports; SpecSpace presents them as read-only review/workbench surfaces.

## Layered Ontology Direction

The next architectural step is to stop treating ontology refs as one flat list
of concepts. The desired model is a layered ontology stack:

```text
ProductOntologyStack
  -> objective       goals, stakeholders, utility functions, tradeoffs
  -> mechanics       deterministic entities, relations, rules, invariants
  -> execution       latency, uncertainty, human error, offline mode, drift
  -> meta            versioning, gaps, deltas, compatibility, invalidation
  -> multi_agent     adaptive actors, adversaries, competitors, AI agents
```

This is an MVP-friendly extension, not a move to a fully formal system. The
first version should add layer metadata and reporting so agents and reviewers
can distinguish:

- a goal from a deterministic domain entity;
- an ideal rule from an execution assumption;
- a data update from a structural ontology change;
- a missing concept from a missing layer/applicability claim;
- a stable decision from a model that is invalidated by changed assumptions.

## Autonomous Idea-To-Spec Direction

The next user-facing milestone is not code generation. The product target is a
fast, visual, metric-controlled path from a raw user idea to a coherent
SpecGraph candidate:

```text
user idea
  -> event-storming intake
  -> ontology/domain/context frame
  -> candidate spec graph
  -> pre-SIB and consistency checks
  -> autonomous repair loop
  -> reviewable graph version
  -> optional canonical PR/merge
```

The human may remain in the loop at the beginning to clarify domain boundaries,
actors, events, commands, policies, and language. After that, the system should
be able to draft and repair the graph without requiring a human for each node.
The authority boundary remains unchanged: generated content is candidate state
until validation and repository governance promote it.

The first real product pilot is `Team Decision Log`. It is intentionally small
but not a mock: teams record decisions, considered options, rationale,
evidence, owners, review triggers, and supersession/conflict relations. This
domain gives the idea-to-spec loop enough structure to exercise event-storming
intake, ontology extraction, candidate graph repair, pre-SIB metrics, and
promotion gates without mixing in SpecGraph bootstrap/self-evolution concerns.

`Team Decision Log` must remain product data. System logic, scripts, route
selection, and deployment profiles should stay generic enough that another idea
can replace the pilot without adding a new product-specific SpecGraph flow.

The desired public deployment shape is one SpecSpace deployment with distinct
workspace routes:

```text
specgraph.space/
  -> SpecGraph bootstrap/showcase workspace

specgraph.space/team-decision-log
  -> Team Decision Log product_idea_to_spec pilot workspace
```

`/team_decision_log` may exist as a compatibility alias, but
`/team-decision-log` is the canonical public route. Each route should resolve to
its own workspace metadata and artifact manifest. The Team Decision Log route
must not expose supervisor self-evolution, bootstrap proposal machinery, local
operator diagnostics, or canonical SpecGraph mutation flows as product-domain
surfaces.

## Graph Versioning And Production Storage Direction

Git remains the preferred canonical version substrate for the graph because it
already provides history, diff, branch review, rollback, signatures/digests, and
auditable publication points. Production SpecSpace should not work as a direct
UI over an arbitrary local folder with `git init`.

The production shape should be a managed graph repository boundary:

```text
SpecSpace UI
  -> Graph Repository Service
  -> Git-backed canonical store
  -> validated specs/runs/proposals
  -> published read model / artifact bundle
```

This separates the read path from the write path:

- SpecSpace reads public-safe static artifacts, indexed read models, and
  version metadata quickly.
- Writes go through candidate workspaces, validation gates, commits, branches,
  reviews, and controlled merge/publish actions.
- No browser workflow should silently mutate `specs/nodes/*.yaml`, write
  ontology packages, or advance canonical graph history without a repository
  service and validation result.
- Product workspace initialization now has an intermediate
  `platform_product_workspace_initialization_execution_request` handoff. It
  lets a hosted/queue-backed worker receive a pinned plan digest and idempotency
  key without letting SpecSpace or the browser execute Platform directly. The
  local `workspace execute-requested-initialization` wrapper is the current
  proof path for that boundary.

## Roadmap

### Immediate Product Workspace Execution Order

The current execution order is:

1. **Quality-guided next action ranking.** SpecSpace now has many accurate
   guided paths and managed operation rows. The next UI coordination slice is a
   deterministic primary action plus secondary actions model that ranks stale
   state, failed operations, blocking clarification/repair, structural-depth
   improvement, approval, promotion, and publication without creating execution
   authority.
2. **Fallback-free real idea clarification.** Implemented across SpecGraph,
   SpecSpace, and Platform. Workspace-bound templates now expose
   `answers_required`, `clarification_not_required`, or
   `clarification_blocked`; Platform can continue a trusted no-answer outcome
   through a fixed SpecGraph target without inventing an answer set.
3. **Durable workspace binding.** Implemented. Platform initialization now
   emits a versioned digest-checked binding across workspace id, display name,
   artifact base, SpecSpace state namespace, run directory, and
   repository/worktree identity. SpecGraph emits producer-owned relative-layout
   evidence, and SpecSpace consumes a public-safe binding projection. Repair,
   approval, promotion, review-status, and publication reports preserve the
   selected binding context. Execution-backed Playwright covers real Platform
   initialization, browser reload, workspace-scoped runs, raw-idea privacy, and
   rejection of foreign or mismatched binding inputs.
4. **Hosted/queue-backed managed execution.** In progress. Platform now owns
   `platform.managed-operation.registry.v1` and queue-safe request/receipt
   contracts for all twelve SpecSpace operations. The next slices add the
   durable queue/store worker, SpecSpace hosted mode, deployment profiles, and
   execution-backed recovery tests. Existing Platform reports remain lifecycle
   authority; queue status remains transport telemetry.
5. **Human-friendly candidate aliases.** SpecGraph should keep stable machine
   ids for refs and promotion paths, but expose readable aliases for candidate
   overview, topology, PR artifacts, and operator-facing diagnostics.
6. **Ontology applicability in product review.** Continue compiler-backed
   layers, `modelApplicability`, and change classification so product
   candidates can explain which ontology layer and applicability frame each
   claim depends on.

Platform should not introduce a separate task-tracking CLI yet. Markdown
roadmaps plus GitHub PR history remain the source of truth. If automation is
needed, prefer small read-only status commands in `scripts/platform.py` over a
new tracker.

### 1. Ontology 039: Layered Ontology Compiler Model

Status: landed in Ontology PR `#59`.

Add first-class layer metadata to the ontology authoring and compiler path.
The minimal contract should include:

- a constrained `OntologyLayer` vocabulary:
  `objective`, `mechanics`, `execution`, `meta`, `multi_agent`;
- optional `layer` fields on concepts, relations, invariants, policies, and
  generated IR entries;
- schema and compiler validation for unknown layer values;
- normalized IR and TypeScript SDK emission of layer metadata;
- compatibility behavior that can identify layer additions/changes.

This belongs in Ontology first because SpecGraph and SpecSpace should consume a
versioned compiler contract rather than invent their own layer vocabulary.

### 2. Ontology 040: Model Applicability And Structural Change Classification

Status: planned in Ontology PR `#60`; implementation is the next compiler-side
slice.

After layer metadata exists, the compiler should define a minimal
`ModelApplicabilityProfile` and review-only structural change classification.
This slice should describe when a model applies, which assumptions support it,
which triggers invalidate it, and whether a compatibility diff is structural,
annotation-only, or applicability-only where the compiler can determine that
without inference.

The initial profile should capture:

- applies-to scopes;
- exclusions;
- execution assumptions;
- invalidation triggers;
- structural versus annotation/applicability change classification.

The contract remains inert review data. It should not authorize runtime
enforcement, ontology package writes, lockfile updates, or SpecGraph canonical
spec mutations.

### 3. SpecGraph Layered Concept Refs And Applicability

Status: partially landed for import, gap/diff review, and SpecAuthor write-gate
context in SpecGraph proposals `0141`, `0142`, and `0143`. The remaining slice
is a graph-side `ModelApplicabilityProfile` import surface once ONT-040 emits
compiler-backed applicability data.

After Ontology emits applicability-aware IR, add graph-side references that
preserve which layer and applicability frame a spec claim uses. The target shape
is a `LayeredConceptRef` or equivalent extension over existing refs, plus a
`ModelApplicabilityProfile` record for specs, generated artifacts, and
supervisor outputs that need scoped validity.

The profile should capture:

- objective refs;
- mechanics package/version refs;
- execution assumptions;
- uncontrolled variables;
- invalidation triggers;
- adaptive or adversarial agents when relevant.

Legacy specs should remain report-only until backfill batches are explicitly
reviewed.

### 4. SpecGraph Layer-Aware Gaps, Diffs, And Backfill

Status: partially landed for layer-aware gap/diff review in SpecGraph proposal
`0142`; applicability-aware gaps/diffs remain future work after ONT-040.

Extend existing gap, diff, validation, owner-decision, and legacy backfill
surfaces so they can report more than "missing concept":

- missing objective;
- missing mechanics rule;
- missing execution assumption;
- missing meta/change contract;
- missing multi-agent actor or adversarial scenario;
- layer mismatch on an existing concept ref;
- `dataChange` versus `structuralChange`.

This is still review-first. The reports should not rewrite specs, accept terms,
update lockfiles, or write project ontology packages.

### 5. SpecSpace Layer Lens And Workbench Review

Status: initial layer lens landed in SpecSpace PR `#249`. Applicability and
invalidation review remain future work after ONT-040 and the SpecGraph import
surface.

Once SpecGraph publishes layer-aware artifacts, SpecSpace should add a layer
lens to the Ontology Workbench:

- filter concepts and relations by layer;
- show layer distribution for the active package;
- show layer-aware gaps/diffs/backfill items;
- connect applicability profiles to affected specs or generated artifacts;
- keep the surface read-only except for SpecSpace-owned acknowledgement state.

### 6. SpecAuthor Agent Layer Classification

Status: deterministic write-gate context landed in SpecGraph proposal `0143`.
Prompt-side invocation behavior is now in the SpecGraph `0146` stack, public
artifact publishing is in `0147`, and the local report-only Agent Passport
behavior declaration is in `0148`. SpecSpace has a matching read-only
invocation review lane in PR `#251`.

Update SpecAuthor-facing prompt and write-gate contracts so generated artifacts
classify new ontology references by layer before graph write:

- objective claims require objective refs;
- deterministic rules require mechanics refs;
- real-world limitations require execution refs;
- compatibility/version claims require meta refs;
- adaptive actors or adversarial behavior require multi-agent refs;
- broad claims must carry explicit applicability and invalidation assumptions.

This strengthens the existing claim-calibration and ontology write-gate line
without forcing legacy specs into strict validation.

The active implementation order for this line is:

1. SpecGraph `0146`: prompt-side authoring flow emits a typed invocation
   artifact from operator intent, active ontology context, generated draft
   artifact, generated artifact contract report, and write-gate report.
2. SpecGraph `0147`: publish the invocation artifact, invocation contract
   report, and authoring-flow report as public-safe `runs` artifacts.
3. SpecSpace: show active frame, selected ontology layers, model applicability
   refs, generated artifact status, write-gate status, invocation contract
   status, and operator decision state in the Ontology Workbench.
4. SpecGraph `0148`: declare SpecAuthorAgent behavior through local
   `x-behaviorPolicies` in Agent Passport, with no runtime enforcement claim.
5. agent-passport: document `x-behaviorPolicies` as an experimental extension
   pattern, not a required core schema field.

### 7. Continue Existing Review Loop

The previously planned review surfaces remain useful and should continue where
they are already in flight:

- source-backed semantic lint input;
- soft supervisor gate evidence;
- prompt-agent ontology context artifacts;
- Ontology owner-decision production;
- SpecSpace acknowledgement workflows.

The layered model should become the semantic contract those surfaces report
against, not a replacement for the review loop.

### 8. Deferred Materialization And Packaging

Defer these until the review loop above is stable:

- canonical `ontology.lock.yaml`;
- automatic imports into `specs/nodes/*.yaml`;
- Platform/Docker packaging for `ontologyc`, prompt packs, and package caches;
- SpecSpace mutation UI;
- automatic ontology package writes from SpecGraph supervisor output.

### 9. Autonomous Idea-To-Spec Loop

Status: implemented through the first active candidate source and public
product workspace route; the next slices are workflow review, Git Service
closure, and real intake.

Add a bounded authoring loop that can create a full candidate graph from a raw
idea without human review on every node:

- landed SpecGraph artifact: event-storming intake for actors, events, commands,
  policies,
  external systems, constraints, risks, and vocabulary questions;
- ontology/domain/context frame construction using project-local ontology
  packages and compiler artifacts;
- landed SpecGraph artifact: candidate spec graph contract with explicit
  non-canonical authority;
- landed SpecGraph artifact: pre-SIB/coherence metrics for completeness,
  contradictions, orphan nodes, ontology coverage, unsupported strong claims,
  unresolved refs, and implementation-readiness signals;
- landed SpecGraph artifact: autonomous repair loop that can revise candidate
  graph state until metrics reach configured thresholds;
- landed SpecSpace workspace route that separates the product pilot from
  SpecGraph bootstrap/showcase state;
- landed SpecGraph promotion gate artifact and SpecSpace read-only promotion
  gate lane;
- next handoff: Git Service backed repository execution and read-model
  publication before any production write UX.

The next implementation target for this line is to remove remaining pilot
specificity from the system layer while keeping Team Decision Log as data:

- publish public-safe candidate artifacts under product workspace manifests;
- keep raw prompt text, private operator notes, and local paths out of public
  bundles;
- make promotion requests target only `product_spec_workspace` repositories;
- preserve `specgraph.space/` as the SpecGraph showcase while allowing product
  routes such as `specgraph.space/team-decision-log` to point at independent
  workspace manifests.

### 10. Git-Backed Graph Repository Service

Status: active next infrastructure layer before production write UX. SpecSpace
now records backend-backed product workspace creation intent as SpecSpace-owned
state. Platform can validate that request into a report-only initialization
plan and execute the ready plan by delegating workspace file creation to the
SpecGraph-owned initializer before appending the Platform catalog entry. The
initialization plan and execution report now expose the versioned
`platform.product-workspace.binding.v1` contract with the selected workspace id,
product run-dir ref, SpecSpace state namespace ref, workspace bundle/manifest
refs, optional static artifact-base URLs, repository identity, and pinned
initialization evidence. Downstream managed-operation reports preserve that
binding context. The remaining gap is service integration: hosted
execution, durable artifact publication, and read-model publication must move
through a Platform/Git Service boundary rather than browser-side mutation. The
local CLI executor is an MVP adapter; production should expose the same
operations through a Git Service rather than relying on an arbitrary local
checkout.

Define a repository service over Git instead of letting SpecSpace mutate a local
checkout directly. The service should own:

- workspace creation and repository binding;
- candidate workspace allocation;
- validation and pre-SIB gate execution;
- branch/commit creation;
- PR/review or controlled auto-merge policy;
- ref ownership, concurrency control, credentials, and audit reports;
- publication of read models and artifact bundles;
- version metadata exposed to SpecSpace.

The first implementation can be simple: a local service or CLI that materializes
only candidate branches and publishes a read-only artifact bundle. Production
can later replace the local storage backend with a managed Git provider,
workspace manager, object storage, or queue-backed worker pool without changing
the UI authority model.

The Git Service must be treated as the durable graph versioning subsystem:
SpecSpace sends intent, SpecGraph supplies gated candidate artifacts, and the
service alone performs repository writes under policy. A local `.git` directory
may be an implementation detail of the MVP, but not the product contract.

### 11. Feature Passport Evidence Authority Decision

Status: deferred until SpecGraph completes the Feature Passport RFC `0.2.0`
producer schema slice.

FeaturePassport PR `#3` tightened `FP-RFC-0001` around receipt hash coverage,
chain scope, successful observations, skipped levels, aggregate claim
evaluation, and passport lifecycle/version pinning. The current cross-repo
sequence should be:

1. SpecGraph proposal `0203`: adopt `FP-RFC-0001` `0.2.0` as the current
   external authority.
2. SpecGraph follow-up: define safe producer schemas for
   `feature_passport_index`, `feature_evidence_index`, receipt projections, and
   claim-evaluation results.
3. SpecSpace follow-up: implement the Feature Evidence viewer contract only from
   those derived artifacts, including skipped/inapplicable levels,
   failure-observation display, aggregate-pending states, and passport-version
   explanation.
4. Platform follow-up: decide whether Platform remains a report producer,
   becomes a receipt normalizer, or becomes a Feature Passport receipt issuer and
   hash-chain authority.

Until that decision is made, Platform must not claim Feature Passport receipt
issuance, evidence-ingestor signing, receipt hash-chain authority, or production
Feature Evidence conformance. Existing durable Platform reports remain
coordination evidence and possible future inputs, not canonical Feature Passport
receipts.

## Preferred Immediate Slice

The previous immediate stack has landed:

```text
SpecGraph 0146 -> SpecGraph 0147 -> SpecSpace invocation lane -> SpecGraph 0148 -> agent-passport x-behaviorPolicies docs
```

This stack keeps Ontology unchanged for now because it only consumes existing
review refs and metadata: layer refs, current model-applicability refs already
present in SpecGraph authoring artifacts, and report-only validation status.
It does not implement the future graph-side
`ModelApplicabilityProfile` import surface.

ONT-040 remains the prerequisite for compiler-backed applicability profiles,
invalidation triggers, and structural change classification that downstream
SpecGraph/SpecSpace applicability dashboards should treat as authoritative.
It no longer blocks the current SpecAuthor prompt-side/Passport work, but it
does block the stronger applicability import and review slices.

Completed Git Service foundation:

1. Platform promoted the local graph repository executor contract into a Git
   Service boundary with explicit repository binding, ref ownership,
   concurrency/audit reports, and queue-ready operation records.
2. Platform added executor orchestration that consumes a promotion request and
   calls `prepare-worktree`, `commit-worktree`, and `open-review` under the
   existing authority gates through that service boundary.
3. SpecSpace added a controlled promotion UI over the promotion request and Git
   Service executor reports.
4. SpecGraph publishes promotion-gate and materialization artifacts in the
   public bundle with stable manifest names for the Git Service handoff.
5. Platform now separates deployment lanes with tracked deployment profiles:
   `product_idea_to_spec_workbench` allows controlled promotion only for product
   spec workspaces, while `specgraph_bootstrap_internal` keeps Git Service
   writes in dry-run-only mode.
6. Platform now owns a controlled Product Repair Rerun execution adapter:
   it validates SpecSpace-owned rerun request state, SpecGraph import preview,
   request gate, and repair session journal before invoking the single
   approved SpecGraph rerun make target, then verifies public-safe bundle
   publication. It does not create branches, commits, pull requests, ontology
   writes, or canonical spec mutations.
7. Platform now exposes an end-to-end Product Repair Rerun smoke contract:
   `product-repair-rerun smoke` runs `plan -> execute -> publish`, emits one
   durable demo report, verifies refreshed repair-session and rerun-report
   digests, and proves public-safe publication without candidate approval or
   Git Service promotion. With `--build-repaired-handoff`, the same smoke also
   runs the fixed repaired handoff target, verifies repaired public artifacts,
   and validates `product-candidate-approval gate` as a read-only readiness
   check without materializing `candidate_approval_decision.json`.
8. SpecSpace now records a candidate approval intent as SpecSpace-owned state,
   and Platform validates that intent through `product-candidate-approval gate`
   before materializing the narrow `candidate_approval_decision.json` handoff.
   The product-level `product-candidate-approval approve` wrapper now records
   that gate/materialize handoff in
   `platform_candidate_approval_execution_report.json` without starting Git
   Service promotion.
   Platform then derives a report-only Graph Repository promotion request via
   `product-candidate-promotion request`, using the approved candidate id and
   materialized paths from the decision artifact rather than requiring the
   operator to retype them.
   The gate requires an approval-ready repair session plus successful
   repair-rerun execution/publication reports and can validate SpecGraph `0177`
   repaired handoff artifacts as first-class inputs when the approval-ready
   session lives in repaired outputs rather than the default `runs/*` chain. It
   still does not start Git Service promotion.
9. Platform now exposes `product-candidate-promotion execute`, a product-aware
   wrapper over `git-service execute-promotion`. It revalidates the promotion
   request, candidate approval decision, deployment profile, and Git Service
   operation contract before preparing the candidate worktree/branch, creating
   the candidate commit, and optionally opening the review pull request.
10. Platform now exposes product-aware post-review operations:
   `product-candidate-promotion review-status` inspects a real review opened by
   the controlled promotion execution, and
   `product-candidate-promotion publish-read-model` publishes only the
   public-safe read model after the review is merged. Auto-merge, Ontology
   writes, accepted ontology terms, and private artifact publication remain out
   of scope.

The previous valuable implementation choices have partially landed: active
candidate source, workspace route selection, controlled promotion UI, deployment
lane isolation, repair-rerun execution, a reproducible rerun smoke contract, and
Metrics-backed idea maturity visibility are now present. The first UX polish
slice landed in SpecSpace: the panel links metric groups to lifecycle sections,
surfaces `next_action` text, and shows rerun trend. The explainability slice now
connects SpecGraph readiness explainers through SpecSpace and Platform reports
so operators see "candidate is blocked because these concrete conditions
remain", not "the score is bad".

The Metrics hardening slice has also landed as a cross-repo contract package:
Metrics is the source of truth for the Idea Maturity schemas, examples,
validator CLI, validation-report schema, and compatibility docs; SpecGraph
emits producer/consumer contract metadata and validator refs; SpecSpace exposes
the metadata in the Product Workspace; and Platform preserves compact sanitized
metadata as report-only telemetry. This means Idea Maturity is no longer just a
local JSON convention inside SpecGraph.

The next valuable implementation choices are:

1. SpecGraph/SpecSpace/Platform: run and preserve a full demo pass for a product
   workspace after the Pre-SIB explainers land. The expected outcome is a
   Product Workspace that shows candidate graph, repair session, Idea Maturity,
   approval readiness, controlled promotion, Git Service execution, review
   status, and publication status as one operator-readable flow.
   The diagnostic pass is now documented in the
   [Product Idea-to-Spec Demo Runbook](product-idea-to-spec-demo-runbook.md).
   The next demo-hardening slices are:

   - **Workspace-scoped demo state hygiene.** Done. SpecSpace now exposes a
     Product Workspace state hygiene surface, and Platform smoke can consume it
     as preflight telemetry before interpreting stale local draft/request/intent
     state.
   - **Generic happy-path repair pack.** Done in the paired SpecGraph slice.
     SpecGraph can materialize workspace/session-consistent repair drafts and
     rerun request state from a `product_workspace_repair_pack` fixture until
     the repaired handoff reaches `ready_for_candidate_approval: true`. Team
     Decision Log is the default demo fixture/alias, not a product-specific
     system flow.
   - **SpecSpace guided product flow.** Done for the local managed lifecycle.
     The Product Workspace now has guided paths for workspace initialization,
     idea intake, clarification continuation, repair rerun, approval, promotion
     request/execution, review status, read-model publication, managed
     operations observability, and managed-mode readiness. The next UX
     refinement is lifecycle-wide action ranking so those paths do not compete
     for the top-level next safe action.
   - **Platform smoke profiles.** Done. `product-repair-rerun smoke` supports
     `strict`, `diagnostic-blocked`, and `happy-path-promotion-dry-run`
     expectation profiles so expected gate blocks are not confused with
     unexpected execution failures.
   - **Product ontology and spec gap review UX.** Done for the current manual
     repair loop. SpecSpace can capture operator-owned drafts for ontology gaps
     and product/spec gaps, validate the structured answers, and pass compatible
     handoff state into the SpecGraph import/rerun path without gaining apply or
     execution authority.
   - **Project-local ontology review completion.** Done for the Team Decision
     Log demo surface. The repair pack can now materialize SpecSpace-owned
     keep-local decisions for required project-local terms, SpecGraph validates
     them through the import preview, Idea Maturity accounts for them as
     project-local review evidence, and Candidate Overview reports the effective
     review status without accepting ontology terms globally.
   - **Full Git lifecycle after overview.** Done. Candidate Overview and
     project-local ontology review accounting no longer prevent the Team Decision
     Log candidate from reaching Platform happy-path repair smoke, candidate
     approval materialization, promotion request creation, Git Service dry-run,
     and a real review pull request. The first controlled non-dry-run pass opened
     SpecGraph PR #662 from `graph-candidate/team-decision-log` with one
     candidate commit; a later full lifecycle smoke merged that review, detected
     the merged review through `product-candidate-promotion review-status`,
     published the public-safe read model through
     `product-candidate-promotion publish-read-model`, and verified that
     SpecSpace can show the completed/published lifecycle state. Auto-merge,
     Ontology writes, accepted ontology terms, and direct SpecSpace Git writes
     remain out of scope.
   - **Production mutable state policy.** Done for the current manual repair
     loop. Product workspace static routing is fixed and `/team-decision-log`
     reads the workspace-specific bundle; SpecSpace surfaces stale/missing
     draft/request/gate state with recommended safe operator actions; and
     consumed source state from the original repair session is treated as usable
     provenance once a repaired handoff records it.
   - **Promotion readiness explainability polish.** Fold into quality-guided
     next action ranking. Blockers should be grouped by owner and next action:
     SpecSpace state, SpecGraph repair/ontology/depth gaps, Platform approval
     gates, and Git Service handoff.
   - **Demo artifact publishing contract.** Done in Platform. The Timeweb
     deployment contract now derives the Team Decision Log demo artifact base
     as `<root artifact base>/workspaces/team-decision-log` unless an explicit
     `WORKSPACE_ID=URL` override is provided, and the production smoke confirmed
     that the workspace manifest and approval-ready repaired handoff are served
     from `https://specgraph.tech/workspaces/team-decision-log` instead of the
     root SpecGraph showcase bundle.
2. Platform: move Product Repair Rerun, candidate approval validation, Git
   Service execution, review-status inspection, and read-model publication from
   local adapter orchestration toward hosted or queue-backed service
   implementation while preserving the same managed operation ids, report
   contracts, idempotency semantics, and authority boundaries.
3. SpecSpace/SpecGraph/Platform: continue hardening the real idea intake
   surface. The raw-entry and answer-continuation handoffs are now in place:
   SpecSpace can store an operator-owned raw idea entry request and later
   clarification answers; SpecGraph can import/materialize those states into
   intake artifacts, a clarified intake session, and an active candidate; and
   Platform can execute the fixed `product-real-idea-intake execute-requested`
   and `product-real-idea-continuation execute-requested` handoffs from
   SpecSpace-owned request artifacts without Git, Ontology, or canonical spec
   mutation authority. Direct execute commands remain operator/debug surfaces
   beneath the request-first UI flow. Project-local ontology review and the
   candidate overview narrative panel are now also connected to Idea Maturity
   and Product Workspace surfaces. Remaining work is product UX polish through
   action ranking, fallback-free clarification templates, human-friendly
   candidate aliases, durable workspace binding, and custom run-dir handoff
   reconciliation against the existing managed-operation promotion dry-run path.
4. Ontology/SpecGraph: continue compiler-backed applicability profile import
   when ONT-040 emits stronger applicability data.

## Operating Notes

- Use the
  [Ontology-SpecGraph-SpecSpace worktree process](ontology-specgraph-specspace-worktree-process.md)
  for parallel work.
- Merge dependency order remains Ontology, then SpecGraph, then SpecSpace,
  unless the downstream repository consumes only a stable fixture or contract
  sample.
- Keep all review surfaces derived and non-canonical until repository-owned
  governance accepts the relevant change.
- Record cross-repo handoffs and blockers through the local `.0al` logging CLI
  when available.
- Treat `x-behaviorPolicies` as semantic/report-only declaration data until a
  repository explicitly implements and tests enforcement semantics.
