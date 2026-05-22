# 0AL Platform

Control plane for local 0AL SpecGraph/SpecSpace/SpecPM workspaces and service
orchestration.

## Purpose

`Platform` is the orchestration repository for a local 0AL workspace. It does not
replace the product repositories:

- `SpecGraph` remains the specification graph engine and supervisor runtime.
- `SpecSpace` remains the visual operator interface.
- `SpecPM` remains the specification package manager and private registry lane.
- `Metrics` remains the metric-pack and research/reference source.

`Platform` coordinates how these services are launched together, how product
workspaces are discovered, and how reusable spec packages move through a
review-first import flow.

## Ownership Boundary

`Platform` may orchestrate product workspace creation, track workspace catalog
entries, and pass operator intent to SpecGraph. It must not independently define
or generate the canonical SpecGraph project contract.

SpecGraph owns:

- `specgraph.project.yaml` schema and validation semantics;
- product workspace initialization safety rules;
- initialization reports such as `runs/product_workspace_initialization.json`;
- root-intent capture boundaries and no-core-mutation guarantees.

Platform owns:

- workspace catalog records;
- service topology and launch profiles;
- local paths and provider wiring;
- calling a SpecGraph-owned initializer when workspace creation needs canonical
  SpecGraph semantics.

## Local Workspace Shape

The intended local layout is:

```text
0AL/
  Platform/
  SpecGraph/
  SpecSpace/
  SpecPM/
  Metrics/
  <product-workspaces>/
```

`0AL/` is an organization checkout root. It does not need to be a git repository.
`Platform/` is the versioned control plane inside that root.

Set `ORG_ROOT` to the absolute path of that organization checkout root before
using the example configs. For example:

```bash
export ORG_ROOT="$HOME/Development/GitHub/0AL"
```

## Product Workspaces

A product workspace is a folder-document managed by SpecGraph:

```text
MyProduct/
  specgraph.project.yaml
  specs/
  docs/proposals/
  runs/
  .specgraph/
```

The default client-facing profile is `product_workspace`. In that mode SpecGraph
should refine the product graph, but it must not mutate SpecGraph core specs,
core tools, or self-evolution surfaces unless an operator explicitly routes the
concern upstream.

## Starter Files

- [PRD.md](PRD.md) defines the MVP product boundary.
- [WORKPLAN.md](WORKPLAN.md) breaks the first implementation into phases.
- [workspaces.example.yaml](workspaces.example.yaml) shows the workspace catalog.
- [schemas/workspace-catalog.schema.json](schemas/workspace-catalog.schema.json)
  defines the workspace catalog validation contract.
- [docs/workspace-catalog.md](docs/workspace-catalog.md) documents workspace
  catalog fields, versioning, and guardrails.
- [services.example.yaml](services.example.yaml) shows managed service metadata.
- [docker-compose.example.yml](docker-compose.example.yml) sketches the local dev
  service topology.

Copy example files to local, untracked variants before putting machine-specific
paths or credentials in them.
