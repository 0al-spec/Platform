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
  - `schemas/workspace-catalog.schema.json`
  - `docs/workspace-catalog.md`
- Add `platform workspace list` or equivalent script.
  - `scripts/platform.py workspace list`
- Add `platform workspace doctor` for path/profile validation.
  - `scripts/platform.py workspace doctor`
- Define how SpecSpace consumes the catalog.

Exit criteria:
- Local catalog can identify active workspaces.
- Missing or unsafe paths are surfaced as diagnostics, not crashes.

## Phase 3: Product Workspace Initialization

- Add a Platform `init-workspace` command or script as an orchestration wrapper.
  - `scripts/platform.py workspace init`
- Delegate canonical workspace creation to a SpecGraph-owned initializer.
- Pass project identity, workspace root, and optional root intent to SpecGraph.
- Record the workspace in the Platform catalog only after SpecGraph returns a
  successful initialization report.
- Surface SpecGraph initialization diagnostics without rewriting or
  second-guessing them.

Exit criteria:
- A new product workspace can be initialized without hand-writing boilerplate.
- The generated workspace uses `product_workspace` by default.
- Platform does not independently generate `specgraph.project.yaml` or duplicate
  SpecGraph initialization safety rules.

## Phase 4: Local Service Launch

- Turn `docker-compose.example.yml` into a runnable local profile.
- Add Platform deploy shortcuts around Docker Compose.
  - `scripts/platform.py deploy render`
  - `scripts/platform.py deploy up`
  - `scripts/platform.py deploy status`
  - `scripts/platform.py deploy down`
- Add `.env.example`.
- Add health checks for SpecGraph, SpecSpace, and SpecPM.
- Add launch/stop/status shortcuts.
- Add a single-node deployment profile so multiple services can run on one
  small VPS instead of requiring one host per service.
- Serve production SpecSpace web as static assets, not through a Vite
  development server.
  - `docker-compose.production-web.example.yml`
  - `scripts/platform.py deploy ... --profile production-web`
- Publish a CI-produced deploy bundle for the `production-web` profile without
  moving Timeweb secrets into Platform.
  - `.github/workflows/deploy-bundle.yml`
  - `scripts/platform.py deploy bundle --output-dir <dir>`
- Track the implementation slices in `docs/local-service-launch-plan.md`.

Exit criteria:
- A local operator can start the factory surface with one command.
- Service status is visible without reading raw logs.
- A solo operator can run the public 0AL surface on one low-cost VPS.

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
