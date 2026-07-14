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
  claiming ownership of the Timeweb Cloud Apps manifest-only path.
  - `.github/workflows/deploy-bundle.yml`
  - `scripts/platform.py deploy bundle --output-dir <dir>`
- Add a Platform-owned Timeweb Cloud Apps manifest-only profile.
  - `scripts/platform.py deploy timeweb-render`
  - `scripts/platform.py deploy timeweb-validate`
- Define the explicit cutover from SpecSpace-owned Timeweb upload to
  Platform-owned Timeweb upload after the image-lock handoff is proven.
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
- Track the deferred Feature Passport evidence authority decision after
  SpecGraph defines `FP-RFC-0001` `0.2.0` producer schemas. Platform must choose
  explicitly between report producer, receipt normalizer, and receipt issuer
  before adding any Feature Passport hash-chain or signing responsibility.

Exit criteria:
- SpecSpace can switch between known workspaces.
- Operator sees whether a workspace is core, product, or private registry backed.
- Platform does not claim Feature Passport receipt authority until a dedicated
  follow-up defines the role, trust keys, chain scope, and verification contract.

## Phase 7: Hosted Managed Execution Production Sign-Off

Completed rollout evidence:

- [x] Provision a clean host from tracked cloud-init and verify SSH, Docker,
  firewall, and `/srv/0al` ownership.
- [x] Configure dedicated DNS and TLS without storing secrets in Git.
- [x] Install file-backed runtime credentials with least-privilege ownership.
- [x] Publish a commit-bound image lock and deploy digest-pinned Platform,
  ingress, and PostgreSQL images through the fail-closed production
  orchestrator.
- [x] Transfer only the workspace binding, portable promotion execution report,
  and queue-safe request for `hosted-operation-canary`.
- [x] Run an initial public-TLS `review_status_execute` rollout canary, verify
  the authoritative report digest, and prove immediate replay preserves attempt
  `1`. This checkpoint is not reused as the causally ordered sign-off canary.
- [x] Automate the fail-closed production backup/isolated restore-smoke cycle
  with guaranteed runtime restart, and add streaming `age` off-host export that
  never writes a plaintext archive to the operator machine.
- [x] Define a versioned three-tier backup-retention policy with validated
  minimum copy counts, target ages, protected states, and disabled automatic
  deletion.
- [x] Run the causally ordered production backup drill: fresh probe, bounded
  backup, isolated restore smoke, encrypted operator-local and iCloud copies,
  and digest verification without a plaintext off-host archive.
- [x] Reboot the production canary host, require a changed boot id, pass strict
  recovery and the post-reboot probe, then replay the identical read-only
  request with the same identity, output refs, and attempt `1`.

Completed sign-off sequence:

- [x] Point a controlled SpecSpace hosted profile at the service and pass
  product smoke with `hosted_managed_ready`, while keeping the deployment
  allowlist at `review_status_execute` only.
- [x] Audit a drained queue, exercise rollback to SpecSpace read-only mode,
  verify no active jobs or locks, stop the worker, and retain rollback evidence.
- [x] Run the combined production sign-off gate over the causally ordered
  preflight, probes, backup/restore, canary, recovery, replay, queue audit,
  hosted SpecSpace smoke, and rollback smoke evidence. The resulting status is
  `production_canary_signed_off` with no diagnostics.

Exit criteria:

- `production_canary_signed_off` is emitted from fresh, causally ordered
  evidence.
- No secrets, raw idea text, local developer paths, or private backup payloads
  are published.
- The production allowlist remains exactly `review_status_execute` until a
  separate rollout proposal approves any expansion.
