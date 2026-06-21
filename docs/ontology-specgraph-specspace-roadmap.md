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

As of 2026-06-21:

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
- The next product direction is an autonomous idea-to-spec workflow: SpecSpace
  should help a user clarify a product idea through an event-storming-like
  intake, then let SpecGraph build a complete candidate specification graph
  under pre-SIB/coherence metrics before any canonical write.

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

## Roadmap

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

Status: active product-facing line after the SpecAuthor prompt-side stack.

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
- landed SpecSpace workspace that shows the candidate graph, metric deltas,
  repair history, and remaining blockers;
- landed SpecGraph promotion gate artifact and SpecSpace read-only promotion
  gate lane;
- next handoff: Git Service backed repository execution before any production
  write UX.

### 10. Git-Backed Graph Repository Service

Status: active next infrastructure layer before production write UX. The local
CLI executor is an MVP adapter; production should expose the same operations
through a Git Service rather than relying on an arbitrary local checkout.

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

The next valuable implementation choices are:

1. Platform: promote the local graph repository executor contract into a Git
   Service boundary with explicit repository binding, ref ownership,
   concurrency/audit reports, and queue-ready operation records.
2. Platform: executor orchestration that consumes a promotion request and calls
   `prepare-worktree`, `commit-worktree`, and `open-review` under the existing
   authority gates through that service boundary.
3. SpecSpace: controlled promotion UI over the promotion request and Git
   Service executor reports.
4. SpecGraph: publish promotion-gate and materialization artifacts in the public
   bundle with stable manifest names for the Git Service handoff.
5. Ontology/SpecGraph: continue compiler-backed applicability profile import
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
