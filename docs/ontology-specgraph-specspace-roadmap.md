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

As of 2026-06-14:

- Ontology PR `#53` is merged: `ontologyc` adapter report artifact line.
- Ontology PR `#54` is merged: Hypercode IR v2 ontology package import.
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

The product intent is to reduce hallucinated terms, misunderstood domain
language, wrong aliases, wrong relation directions, and hidden missing concepts
in agent-generated specs, proposals, and review surfaces.

## Roadmap

### 1. SpecGraph 0116: Source-Backed Semantic Lint Input

Move the full semantic lint report off policy fixture terms and onto a
source-backed input artifact, likely:

```text
runs/ontology_semantic_lint_input.json
```

The input should collect declared semantic terms from tracked SpecGraph
proposal, spec, or supervisor output sources and preserve:

- source id and kind;
- repository path;
- text digest;
- source spans;
- detected terms and optional ontology refs.

This remains an MVP guardrail. It must not become arbitrary NLP parsing, prompt
execution, ontology package mutation, ontology lockfile update, or canonical
SpecGraph mutation.

### 2. SpecGraph 0117: Soft Supervisor Gate Wiring

Wire `runs/ontology_supervisor_semantic_gate.json` into ordinary targeted
supervisor runs as soft review evidence first.

The first integration should:

- warn or route `review_pending` rather than hard-block every generation;
- preserve current hard blockers for deprecated terms and relation conflicts;
- keep gate decisions explicit in run artifacts;
- avoid hidden prompt-pack execution inside supervisor behavior.

### 3. SpecGraph 0118: Prompt-Agent Ontology Context Artifact

Add a typed invocation boundary for agent generation that receives the
ontology semantic context pack before drafting.

The artifact should carry:

- accepted terms and relations;
- aliases and deprecated terms;
- unresolved gaps;
- package refs, versions, and digests;
- prompt input/output refs and failure modes.

This is grounding input, not proof of correctness and not permission for agents
to write Ontology packages or canonical specs.

### 4. Ontology Owner Decision Production

Add the Ontology-side path that turns reviewed SpecGraph delta candidates into
real owner decision artifacts.

The decision path should require:

- `ontologyc check`;
- golden-intent or repeatability evidence where applicable;
- Ontology governance decision evidence;
- source, version, and digest references.

Accepted, rejected, and clarification decisions can then flow back into the
existing SpecGraph `0114` and `0115` read-only decision surfaces.

### 5. SpecSpace Acknowledgement Workflow

Add SpecSpace-owned acknowledgement or operator workflow state for owner
decisions and semantic gate review.

This may let reviewers mark that they inspected:

- accepted/rejected owner decisions;
- linked evidence;
- affected review items;
- before/after semantic status.

It must not mutate Ontology packages, SpecGraph canonical specs, or import
locks.

### 6. Deferred Materialization And Packaging

Defer these until the review loop above is stable:

- canonical `ontology.lock.yaml`;
- automatic imports into `specs/nodes/*.yaml`;
- Platform/Docker packaging for `ontologyc`, prompt packs, and package caches;
- SpecSpace mutation UI;
- automatic ontology package writes from SpecGraph supervisor output.

## Preferred Immediate Slice

The current productive slice is:

```text
SpecGraph 0116: source-backed semantic lint input + report wiring + tests
```

After that lands, the next most valuable slice is a conservative
`0117` supervisor gate integration in soft-review mode.

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
