# 0AL Platform

Control plane for local 0AL SpecGraph/SpecSpace/SpecPM workspaces and service
orchestration.

## Purpose

`Platform` is the orchestration repository for a local 0AL workspace. It does not
replace the product repositories:

- `SpecGraph` remains the specification graph engine and supervisor runtime.
- `ContextBuilder` / `SpecSpace` remains the visual operator interface.
- `SpecPM` remains the specification package manager and private registry lane.
- `Metrics` remains the metric-pack and research/reference source.

`Platform` coordinates how these services are launched together, how product
workspaces are discovered, and how reusable spec packages move through a
review-first import flow.

## Local Workspace Shape

The intended local layout is:

```text
0AL/
  Platform/
  SpecGraph/
  ContextBuilder/
  SpecPM/
  Metrics/
  <product-workspaces>/
```

`0AL/` is an organization checkout root. It does not need to be a git repository.
`Platform/` is the versioned control plane inside that root.

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
- [services.example.yaml](services.example.yaml) shows managed service metadata.
- [docker-compose.example.yml](docker-compose.example.yml) sketches the local dev
  service topology.

Copy example files to local, untracked variants before putting machine-specific
paths or credentials in them.
