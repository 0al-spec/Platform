# 0AL Platform Workplan

## Phase 1: Foundation

- Define repository purpose and boundaries.
- Add portable example configs.
- Establish local-file naming and `.gitignore` policy.
- Document service ownership:
  - `SpecGraph`: engine/supervisor/spec runtime;
  - `SpecSpace`: visual operator UI;
  - `SpecPM`: package manager and private registry;
  - `Metrics`: metric-pack source.

Exit criteria:
- README, PRD, WORKPLAN, and example configs exist.
- No machine-specific paths or credentials are tracked.

## Phase 2: Workspace Catalog

- Define stable catalog schema for product workspaces.
- Add `platform workspace list` or equivalent script.
- Add `platform workspace doctor` for path/profile validation.
- Define how SpecSpace consumes the catalog.

Exit criteria:
- Local catalog can identify active workspaces.
- Missing or unsafe paths are surfaced as diagnostics, not crashes.

## Phase 3: Product Workspace Initialization

- Add `init-workspace` command or script.
- Generate `specgraph.project.yaml`.
- Create `specs/`, `docs/proposals/`, `runs/`, and `.specgraph/`.
- Optionally seed a root intent/proposal.

Exit criteria:
- A new product workspace can be initialized without hand-writing boilerplate.
- The generated workspace uses `product_workspace` by default.

## Phase 4: Local Service Launch

- Turn `docker-compose.example.yml` into a runnable local profile.
- Add `.env.example`.
- Add health checks for SpecGraph, SpecSpace, and SpecPM.
- Add launch/stop/status shortcuts.

Exit criteria:
- A local operator can start the factory surface with one command.
- Service status is visible without reading raw logs.

## Phase 5: Private SpecPM Imports

- Define private registry expectations.
- Add import discovery from the workspace catalog.
- Support import preview as the first-class boundary.
- Require human approval before materialization into a product graph.

Exit criteria:
- One product workspace can discover a SpecPM package exported by another
  workspace or repo.
- Import remains review-first and does not silently mutate canonical specs.

## Phase 6: SpecSpace Integration

- Expose workspace catalog to SpecSpace.
- Add project switcher requirements.
- Add per-workspace provider configuration.
- Make product/core boundary visible in the UI.

Exit criteria:
- SpecSpace can switch between known workspaces.
- Operator sees whether a workspace is core, product, or private registry backed.
