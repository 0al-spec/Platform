# 0AL Platform PRD

## Summary

0AL Platform is the local control plane for operating SpecGraph, SpecSpace,
SpecPM, Metrics, and product workspaces as one software factory.

The MVP is intentionally small: it defines a workspace catalog, service topology,
and local launch conventions. It does not implement a hosted multi-tenant
service, authentication, billing, or automatic cross-repo mutation.

## Problem

SpecGraph is becoming useful outside its own repository, but a user currently
needs to manually know:

- where product workspaces should live;
- how to write `specgraph.project.yaml`;
- how to launch SpecGraph, SpecSpace, and SpecPM together;
- how to avoid accidentally running SpecGraph self-evolution against a client
  project;
- how reusable spec modules should move between projects.

Without a control plane, every project becomes ad hoc local scripting.

## Goals

- Define `0AL/` as a local organization workspace root.
- Provide a versioned `Platform/` repo for orchestration.
- Track product workspaces through a portable catalog.
- Track managed services and expected local ports through service metadata.
- Support `product_workspace` as the safe default for external/client projects.
- Make private SpecPM imports review-first rather than automatic graph mutation.
- Keep product workspaces isolated from SpecGraph core self-evolution.

## Non-Goals

- Do not turn SpecGraph into the platform orchestrator.
- Do not make the entire `0AL/` superdirectory a git repository.
- Do not auto-import SpecPM packages into canonical product specs.
- Do not store secrets or machine-specific absolute paths in tracked files.
- Do not require Docker for every local operation; Docker is one launch option.

## Users

- Solo operator running several local product workspaces.
- Developer using SpecSpace to inspect and guide a product graph.
- SpecPM package author publishing reusable spec boundaries locally.
- Future small team sharing a private package registry and workspace conventions.

## MVP Capabilities

1. Workspace catalog
   - list known product workspaces;
   - identify profile, path, status, and provider settings;
   - distinguish core repos from product workspaces.

2. Service topology
   - describe SpecGraph, SpecSpace, SpecPM, and Metrics checkouts;
   - pin local expected ports and health endpoints;
   - avoid hardcoded user-specific paths.

3. Local launch profile
   - provide a `docker-compose` starting point;
   - keep examples portable and safe;
   - allow services to run from sibling checkouts.

4. SpecPM private registry lane
   - describe local/private registry use;
   - require import preview and human review before materialization;
   - keep package boundary identity versioned.

5. Product workspace guardrails
   - default external workspaces to `product_workspace`;
   - block ordinary SpecGraph core mutation;
   - route self-evolution concerns upstream by explicit operator decision.

## Success Criteria

- A new developer can understand the role split between Platform, SpecGraph,
  SpecSpace, SpecPM, and Metrics from this repo alone.
- Example configs can be copied and adapted without editing tracked files.
- SpecSpace can eventually read a workspace catalog without hardcoding local
  project paths.
- SpecGraph can eventually initialize a product workspace from Platform metadata.
- SpecPM private registry usage remains review-first.

## Risks

- Platform could become a dumping ground for product logic. Keep it limited to
  orchestration, catalog, launch, and integration contracts.
- Local paths can leak into git. Keep local variants ignored and examples
  placeholder-based.
- Cross-project imports can create hidden coupling. Keep SpecPM imports explicit,
  versioned, previewed, and human-approved.
