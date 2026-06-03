# Local Service Launch Plan

## Context

Platform is the local control plane for running the 0AL service set from sibling
checkouts under one operator-managed `0AL/` root. Phase 1 through Phase 3
established repository boundaries, workspace catalog validation, and delegated
product workspace initialization.

Phase 4 makes local service launch an explicit Platform responsibility without
collapsing service ownership. Platform owns topology, Compose wiring, local
operator commands, and deployment profiles. SpecGraph, SpecSpace, and SpecPM
continue to own their own runtime contracts.

## Target Outcome

A solo operator can start, inspect, and stop the local 0AL surface with one
Platform command surface:

```bash
scripts/platform.py deploy render
scripts/platform.py deploy up
scripts/platform.py deploy status
scripts/platform.py deploy down
```

The default profile should run on one machine and map cleanly to a low-cost VPS
deployment later. The canonical production path is a Compose-managed set of
separate services, not one long-running all-in-one process.

## Implementation Slices

### Slice 1: Runnable Compose Entry Point

Status: implemented in PR #10.

- Add `.env.example` for local knobs.
- Add `deploy render/up/status/down` wrappers around Docker Compose.
- Parameterize ports, images, and public API URLs.
- Keep tracked Compose files portable and placeholder-based.
- Make `http://127.0.0.1:8081/`, `http://127.0.0.1:8001/`, and
  `http://127.0.0.1:5173/` useful operator entry points.

### Slice 2: Health And Readiness

Status: implemented in PR #10.

- Add Compose health checks for SpecPM public index, SpecSpace API, and
  SpecSpace web.
- Keep health checks dependency-light: use Python in Python containers and Node
  in Node containers instead of requiring extra curl/wget packages.
- Treat `deploy status` as the operator's first readiness view.

### Slice 3: Production Static Web Profile

Status: implemented in PR #11.

- Stop treating the Vite development server as the production shape.
- Add a production web service that builds SpecSpace static assets and serves
  them through a small static server or reverse proxy.
- Keep the development profile available for local iteration.
- Keep Timeweb upload secrets in the repository that performs the upload until
  Platform CI explicitly takes over deployment ownership.
- Support local port override through `SPECSPACE_WEB_PORT` so this profile can
  be verified even when a developer already has a Vite server on the default
  port.

### Slice 4: CI-Produced Compose Artifact

Status: implemented in PR #12.

- Make CI publish a portable deployment bundle that Compose-capable single-node
  hosts can consume.
- Include the base Compose file, the production-web overlay, `.env.example`,
  a manifest, and operator instructions.
- Validate the bundled Compose config in CI before uploading the artifact.
- Keep machine-local `.env` values outside git.
- Prefer image tags and immutable inputs over rebuilding from live checkouts on
  the VPS.
- Do not treat this bundle as the current Timeweb Cloud Apps manifest. SpecSpace
  currently owns that manifest-only path because it avoids bind mounts and
  required environment interpolation.

### Slice 5: Image Hardening

Status: planned.

- Move startup dependency installation into owned images.
- Pin image tags and make runtime containers start quickly.
- Preserve separate logs and health checks per service.

### Slice 6: Timeweb Manifest Ownership

Status: in progress.

- Add a Platform-owned Timeweb Cloud Apps manifest renderer.
- Preserve the existing Timeweb constraints from SpecSpace:
  - manifest-only tree;
  - digest-pinned API/UI images;
  - no source builds;
  - no volumes;
  - no required environment interpolation.
- Accept a `platform_service_image_lock` artifact so service-producing CI can
  hand digest-pinned image refs to the Platform renderer without moving deploy
  secrets or rebuilding services in Platform.
- Keep SpecSpace responsible for producing API/UI images and health endpoints.
- Switch SpecSpace CI to call the Platform renderer only after the Platform
  manifest contract is validated in CI.

## Guardrails

- Do not require one VPS per service.
- Do not make all-in-one images the primary deployment contract.
- Do not store secrets, tokens, private keys, or machine-local absolute paths in
  tracked files.
- Do not make Platform implement SpecGraph, SpecSpace, or SpecPM business
  logic.
- Do not hide service ownership by merging components into one process.

## Validation

For every local launch slice:

```bash
python3 -m unittest discover -s tests
python3 -m compileall scripts/platform.py tests
git diff --check
ORG_ROOT=/path/to/0AL scripts/platform.py deploy render
ORG_ROOT=/path/to/0AL scripts/platform.py deploy up
ORG_ROOT=/path/to/0AL scripts/platform.py deploy status
curl -fsS http://127.0.0.1:8001/api/v1/health
curl -fsS http://127.0.0.1:8081/v0/status/index.json
curl -fsS http://127.0.0.1:5173/
```

When the SpecPM browser entry point changes, also verify:

```bash
curl -fsS http://127.0.0.1:8081/
```
