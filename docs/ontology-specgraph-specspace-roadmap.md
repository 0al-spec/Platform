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

As of 2026-06-13:

- Ontology PR `#53` is merged: `ontologyc` adapter report artifact line.
- Ontology PR `#54` is merged: Hypercode IR v2 ontology package import.
- SpecGraph proposal `0060` defines the external ontology import plane.
- SpecGraph `docs/ontologyc_adapter_report_contract.md` defines the
  `ontologyc validate-specgraph` adapter report boundary.
- SpecGraph proposal `0100` records the operator intent for
  ontology-grounded semantic control.
- SpecGraph proposals `0103` through `0106` are implemented:
  - `0103` semantic control policy;
  - `0104` semantic context pack;
  - `0105` semantic lint report;
  - `0106` ontology delta candidate review packet.

The product intent is to reduce hallucinated terms, misunderstood domain
language, wrong aliases, wrong relation directions, and hidden missing concepts
in agent-generated specs, proposals, and review surfaces.

## Roadmap

### 1. SpecGraph 0108: Semantic Review Surface

Create the next SpecGraph slice as a stable derived artifact, likely:

```text
runs/ontology_semantic_review_surface.json
```

The surface should combine:

- `runs/ontology_semantic_context_pack.json`;
- `runs/ontology_semantic_lint_report.json`;
- `runs/ontology_delta_candidate_review_packet.json`;
- review actions and authority boundaries.

This slice should not add SpecSpace UI, mutation routes, ontology lockfiles, or
canonical spec mutations.

### 2. SpecSpace Read-Only Consumer

After SpecGraph publishes a stable review surface contract, add a SpecSpace
consumer that renders the surface read-only.

The UI/API may show:

- accepted ontology terms;
- accepted aliases;
- deprecated terms;
- unknown terms;
- relation conflicts;
- ontology gaps;
- ontology delta candidates;
- review-intent actions such as approve, reject, or clarify.

SpecSpace must not become the authority for accepted ontology changes and must
not write Ontology packages or SpecGraph canonical specs.

### 3. SpecGraph Supervisor Semantic Gate

Add a bounded supervisor integration that consumes the semantic artifacts as
gate evidence:

- before generation, build or load the semantic context pack;
- after generation, run semantic lint over the generated output or candidate
  fixture;
- block or route review when relation conflicts, deprecated terms, or unknown
  critical terms appear;
- emit ontology gaps or delta candidate review packets for missing concepts.

This must remain a typed artifact boundary. Do not hide prompt-pack execution
inside the supervisor as implicit behavior.

### 4. Ontology Delta Draft Intake

Add an Ontology-side contract for receiving an approved SpecGraph ontology
delta candidate and turning it into a reviewable `DomainOntologyPackage` draft
or patch candidate.

This intake should require:

- `ontologyc check`;
- golden-intent or repeatability evidence where applicable;
- Ontology governance decision evidence;
- source, version, and digest references.

An approved SpecGraph candidate is input to Ontology owner review. It is not
automatic acceptance.

### 5. Closed-Loop Evidence Back To SpecGraph

After Ontology governance, SpecGraph should be able to consume evidence that a
candidate was accepted, rejected, or sent back for clarification.

The returned evidence should include:

- Ontology source ref and digest;
- `ontologyc` adapter/report evidence;
- governance decision reference;
- updated normalized IR or package ref;
- gap resolution or rejection state.

This closes the review loop without making SpecGraph the owner of Ontology
package authority.

### 6. Deferred Materialization And Packaging

Defer these until the review loop above is stable:

- canonical `ontology.lock.yaml`;
- automatic imports into `specs/nodes/*.yaml`;
- Platform/Docker packaging for `ontologyc`, prompt packs, and package caches;
- SpecSpace mutation UI;
- automatic ontology package writes from SpecGraph supervisor output.

## Preferred Next PR

The next productive PR should be:

```text
SpecGraph 0108: semantic review surface contract + artifact builder + tests
```

It is the most direct bridge from implemented SpecGraph slices `0103` through
`0106` to SpecSpace and supervisor usage.

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
